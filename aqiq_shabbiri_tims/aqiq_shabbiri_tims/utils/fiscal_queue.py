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
        
        # Enqueue the job
        enqueue(
            method="aqiq_shabbiri_tims.utils.fiscal_queue.process_fiscalization",
            queue="short" if retry_count == 0 else "long",
            timeout=300,
            event="fiscal_device",
            queue_doc=queue_doc.name,
            invoice_name=invoice_name,
            retry_count=retry_count,
            now=retry_count == 0  # Immediate processing for first attempt
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
        queue.status = "Processing"
        queue.save()
        
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
        queue.status = "Completed"
        queue.response = frappe.as_json(response)
        queue.completion_time = datetime.now()
        queue.save()
        
        frappe.db.commit()
        
    except Exception as e:
        frappe.db.rollback()
        
        if retry_count < 3:  # Allow 3 retries
            # Schedule retry after exponential backoff
            delay = 300 * (2 ** retry_count)  # 5min, 10min, 20min
            
            queue.status = "Failed"
            queue.error = str(e)
            queue.save()
            
            # Enqueue retry
            enqueue_fiscalization(invoice_name, retry_count + 1)
        else:
            queue.status = "Failed"
            queue.error = str(e)
            queue.save()
            
            frappe.log_error(
                title=_("Fiscalization Failed After Retries"),
                message=f"Invoice: {invoice_name}\nError: {str(e)}"
            )
        
        frappe.db.commit()

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