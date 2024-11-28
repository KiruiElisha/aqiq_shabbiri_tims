import frappe
from frappe import _
import json

def validate_fiscal_fields(doc):
    """Validate fiscal fields before submission"""
    if doc.is_return and not doc.return_against:
        frappe.throw(_("Return Against invoice is mandatory for Credit Notes"))

def on_submit(doc, method):
    """Directly fiscalize invoice on submit if enabled"""
    if not doc.custom_is_fiscalized and not doc.is_return:
        fiscal_settings = frappe.get_doc("Fiscal Device Settings")
        if not fiscal_settings.enable_device or not fiscal_settings.fiscalize_invoices_on_submit:
            return  # Exit if device is not enabled or fiscalization on submit is not enabled
        if not fiscal_settings.enable_device:
            frappe.throw(_("Fiscal Device is not enabled in settings"))

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

        except Exception as e:
            frappe.log_error(
                title=_("Failed to Fiscalize Invoice"),
                message=str(e)
            )
            frappe.throw(_("Failed to fiscalize invoice: {0}").format(str(e)))

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
        if not fiscal_settings.enable_device or not fiscal_settings.fiscalize_invoices_on_submit:
            frappe.throw(_("Fiscal Device is not enabled in settings or fiscalization on submit is not enabled"))

        # Directly fiscalize
        on_submit(invoice, None)

        return {
            'success': True,
            'message': _('Invoice fiscalized successfully')
        }

    except Exception as e:
        frappe.log_error(
            title=_("Failed to Fiscalize Invoice"),
            message=str(e)
        )
        frappe.throw(_("Failed to fiscalize invoice: {0}").format(str(e))) 