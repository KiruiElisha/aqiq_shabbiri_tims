import frappe
from frappe import _
from frappe.utils.background_jobs import enqueue
from datetime import datetime, timedelta

def enqueue_fiscalization(invoice_name, retry_count=0):
    """Enqueue invoice fiscalization"""
    try:
        # Check if already in queue
        if frappe.db.exists("Fiscal Queue", {"invoice": invoice_name, "status": ["in", ["Queued", "Processing"]]}):
            return
            
        # Create queue entry
        queue_doc = frappe.get_doc({
            "doctype": "Fiscal Queue",
            "invoice": invoice_name,
            "status": "Queued",
            "retry_count": retry_count,
            "creation": datetime.now()
        }).insert(ignore_permissions=True)
        
        # Enqueue the job with correct path and parameters
        enqueue(
            method="aqiq_shabbiri_tims.aqiq_shabbiri_tims.utils.fiscal_queue.process_fiscalization",
            queue="default",
            timeout=300,
            job_name=f"fiscal_invoice_{invoice_name}",
            kwargs={
                "queue_doc": queue_doc.name,
                "invoice_name": invoice_name,
                "retry_count": retry_count
            },
            is_async=True
        )
        
    except Exception as e:
        frappe.log_error(
            title=_("Failed to Enqueue Fiscalization"),
            message=str(e)
        )

def process_fiscalization(queue_doc, invoice_name, retry_count=0):
    """Process fiscalization in background"""
    try:
        if not frappe.db.exists("Sales Invoice", invoice_name):
            raise Exception("Invoice not found")
            
        queue = frappe.get_doc("Fiscal Queue", queue_doc)
        if queue.status == "Completed":
            return
            
        queue.db_set('status', 'Processing')
        frappe.db.commit()
        
        invoice = frappe.get_doc("Sales Invoice", invoice_name)
        fiscal_settings = frappe.get_doc("Fiscal Device Settings")
        
        # Format and send invoice data
        invoice_data = fiscal_settings.format_invoice_data(
            invoice, 
            invoice.items,
            is_inclusive=(invoice.get("taxes") or [{}])[0].get("included_in_print_rate", True)
        )
        
        response = fiscal_settings.sign_invoice(invoice_data)
        
        # Update invoice
        invoice.db_set('custom_fiscal_invoice_number', response.get('cu_invoice_number'))
        invoice.db_set('custom_fiscal_verification_url', response.get('verify_url'))
        invoice.db_set('custom_is_fiscalized', 1)
        
        # Update queue status
        queue.db_set('status', 'Completed')
        queue.db_set('response', frappe.as_json(response))
        queue.db_set('completion_time', datetime.now())
        
        frappe.db.commit()
        
    except Exception as e:
        frappe.db.rollback()
        
        if retry_count < 3:
            delay = 300 * (2 ** retry_count)
            queue.db_set('status', 'Failed')
            queue.db_set('error', str(e))
            frappe.db.commit()
            enqueue_fiscalization(invoice_name, retry_count + 1)
        else:
            queue.db_set('status', 'Failed')
            queue.db_set('error', str(e))
            frappe.db.commit()
            frappe.log_error(
                title=_("Fiscalization Failed After Retries"),
                message=f"Invoice: {invoice_name}\nError: {str(e)}"
            )

def process_failed_queue():
    """Process failed fiscalizations"""
    failed_queue = frappe.get_all(
        "Fiscal Queue",
        filters={
            "status": "Failed",
            "retry_count": ["<", 3],
            "modified": ["<", datetime.now() - timedelta(minutes=30)]
        },
        pluck="name"
    )
    
    for queue_name in failed_queue:
        queue = frappe.get_doc("Fiscal Queue", queue_name)
        enqueue_fiscalization(queue.invoice, queue.retry_count + 1) 