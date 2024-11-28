import frappe
from frappe import _
import json
from datetime import datetime

def validate_fiscal_fields(doc):
    """Validate fiscal fields before submission"""
    if doc.is_return and not doc.return_against:
        frappe.throw(_("Return Against invoice is mandatory for Credit Notes"))

def on_submit(doc, method):
    """Directly fiscalize invoice on submit if enabled"""
    if not doc.custom_is_fiscalized and not doc.is_return:
        fiscal_settings = frappe.get_doc("Fiscal Device Settings")
        if not fiscal_settings.enable_device or not fiscal_settings.fiscalize_invoices_on_submit:
            return

        # Create Fiscal Queue entry
        queue_doc = frappe.get_doc({
            "doctype": "Fiscal Queue",
            "invoice": doc.name,
            "status": "Queued",
            "retry_count": 0
        })
        queue_doc.insert(ignore_permissions=True)

        try:
            # Format invoice data
            invoice_data = fiscal_settings.format_invoice_data(
                doc, doc.items,
                is_inclusive=(doc.get("taxes") or [{}])[0].get("included_in_print_rate", True)
            )

            # Log the payload
            frappe.logger().debug(f"Fiscalization Payload: {json.dumps(invoice_data, indent=2)}")

            # Sign invoice
            response = fiscal_settings.sign_invoice(invoice_data)

            # Update fiscal details with custom fields
            doc.db_set('custom_fiscal_invoice_number', response.get('cu_invoice_number'))
            doc.db_set('custom_fiscal_verification_url', response.get('verify_url'))
            doc.db_set('custom_is_fiscalized', 1)

            # Update Fiscal Queue with success
            queue_doc.status = "Completed"
            queue_doc.response = json.dumps(response, indent=2)
            queue_doc.completion_time = datetime.now()
            queue_doc.save(ignore_permissions=True)

        except Exception as e:
            error_msg = str(e)
            frappe.log_error(
                title=_("Failed to Fiscalize Invoice"),
                message=error_msg
            )
            
            # Update Fiscal Queue with error
            queue_doc.status = "Failed"
            queue_doc.error = error_msg
            queue_doc.retry_count += 1
            queue_doc.save(ignore_permissions=True)
            
            frappe.throw(_("Failed to fiscalize invoice: {0}").format(error_msg))

@frappe.whitelist()
def fiscalize_submitted_invoice(invoice_name):
    """Fiscalize a submitted invoice"""
    try:
        invoice = frappe.get_doc("Sales Invoice", invoice_name)

        if invoice.docstatus != 1:
            frappe.throw(_("Invoice must be submitted to fiscalize"))

        if invoice.custom_is_fiscalized:
            frappe.throw(_("Invoice is already fiscalized"))

        # Create Fiscal Queue entry
        queue_doc = frappe.get_doc({
            "doctype": "Fiscal Queue",
            "invoice": invoice_name,
            "status": "Queued",
            "retry_count": 0
        })
        queue_doc.insert(ignore_permissions=True)

        fiscal_settings = frappe.get_doc("Fiscal Device Settings")
        if not fiscal_settings.enable_device:
            frappe.throw(_("Fiscal Device is not enabled in settings"))

        try:
            # Format invoice data
            invoice_data = fiscal_settings.format_invoice_data(
                invoice, invoice.items,
                is_inclusive=(invoice.get("taxes") or [{}])[0].get("included_in_print_rate", True)
            )

            # Sign invoice
            response = fiscal_settings.sign_invoice(invoice_data)

            # Update invoice fiscal details
            invoice.db_set('custom_fiscal_invoice_number', response.get('cu_invoice_number'))
            invoice.db_set('custom_fiscal_verification_url', response.get('verify_url'))
            invoice.db_set('custom_is_fiscalized', 1)

            # Update Fiscal Queue with success
            queue_doc.status = "Completed"
            queue_doc.response = json.dumps(response, indent=2)
            queue_doc.completion_time = datetime.now()
            queue_doc.save(ignore_permissions=True)

            return {
                'success': True,
                'message': _('Invoice fiscalized successfully'),
                'response': response
            }

        except Exception as e:
            error_msg = str(e)
            frappe.log_error(
                title=_("Failed to Fiscalize Invoice"),
                message=error_msg
            )
            
            # Update Fiscal Queue with error
            queue_doc.status = "Failed"
            queue_doc.error = error_msg
            queue_doc.retry_count += 1
            queue_doc.save(ignore_permissions=True)
            
            frappe.throw(_("Failed to fiscalize invoice: {0}").format(error_msg))

    except Exception as e:
        frappe.log_error(
            title=_("Failed to Fiscalize Invoice"),
            message=str(e)
        )
        frappe.throw(_("Failed to fiscalize invoice: {0}").format(str(e))) 