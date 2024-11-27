import frappe
from frappe import _
from ..utils.fiscal_queue import enqueue_fiscalization

def validate_fiscal_fields(doc):
    """Validate fiscal fields before submission"""
    if doc.is_return and not doc.return_against:
        frappe.throw(_("Return Against invoice is mandatory for Credit Notes"))

def on_submit(doc, method):
    """Queue fiscalization on submit"""
    if not doc.custom_is_fiscalized and not doc.is_return:
        fiscal_settings = frappe.get_doc("Fiscal Device Settings")
        if not fiscal_settings.enable_device:
            return
            
        enqueue_fiscalization(doc.name)

@frappe.whitelist()
def fiscalize_submitted_invoice(invoice_name):
    """Fiscalize a submitted invoice"""
    try:
        invoice = frappe.get_doc("Sales Invoice", invoice_name)
        
        if invoice.docstatus != 1:
            frappe.throw(_("Invoice must be submitted to fiscalize"))
            
        if invoice.custom_is_fiscalized:
            frappe.throw(_("Invoice is already fiscalized"))
            
        fiscal_settings = frappe.get_doc("Fiscal Device Settings")
        if not fiscal_settings.enable_device:
            frappe.throw(_("Fiscal Device is not enabled in settings"))
            
        enqueue_fiscalization(invoice_name)
        
        return {
            'success': True,
            'message': _('Invoice queued for fiscalization')
        }
        
    except Exception as e:
        frappe.log_error(
            title=_("Failed to Queue Fiscalization"),
            message=str(e)
        )
        frappe.throw(_("Failed to queue fiscalization: {0}").format(str(e))) 