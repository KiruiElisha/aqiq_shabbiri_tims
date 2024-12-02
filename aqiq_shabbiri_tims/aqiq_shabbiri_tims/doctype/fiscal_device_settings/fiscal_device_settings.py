# Copyright (c) 2024, Ronoh and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
import requests
from requests.exceptions import RequestException
import json
import datetime

from frappe import _
from frappe.utils import flt
class FiscalDeviceSettings(Document):
    def get_dashboard_data(self):
        return {
            'fieldname': 'fiscal_device',
            'non_standard_fieldnames': {},
            'internal_links': {},
            'transactions': [
                {
                    'label': _('Device Operations'),
                    'items': ['Test Connection']
                }
            ]
        }

    def get_connection_status(self):
        if not self.device_ip or not self.port:
            return {
                'status': 'Not Configured',
                'color': 'red',
                'message': _('Device IP and Port not configured')
            }
        
        result = test_connection(self.device_ip, self.port)
        if result.get('success'):
            return {
                'status': 'Connected',
                'color': 'green',
                'message': _('Device is connected and ready')
            }
        else:
            return {
                'status': 'Disconnected',
                'color': 'red',
                'message': result.get('error', _('Connection failed'))
            }

    def get_api_headers(self):
        """Get the required headers for API calls"""
        return {
            'Content-Type': 'application/json',
            'Authorization': self.bearer_token  # Fetch bearer token from the doctype
        }

    def throw_error(self, message, details=None):
        """Throw error with optional debug details"""
        if self.debug_mode and details:
            full_message = f"{message}\n\nDebug Details:\n{details}"
            frappe.throw(_(full_message))
        else:
            frappe.throw(_(message))

    def sign_invoice(self, invoice_data, is_inclusive=True, retries=3):
        """
        Sign an invoice with the fiscal device
        Args:
            invoice_data (dict): Invoice data to be signed
            is_inclusive (bool): Whether prices are VAT inclusive
            retries (int): Number of retry attempts
        """
        if not self.enable_device:
            frappe.throw(_("Fiscal Device is not enabled"))

        if not self.device_ip or not self.port:
            frappe.throw(_("Device IP and Port must be configured"))

        endpoint = "invoice+1" if is_inclusive else "invoice+2"
        url = f"http://{self.device_ip}:{self.port}/api/sign?{endpoint}"

        for attempt in range(retries):
            try:
                response = requests.post(
                    url=url,
                    headers=self.get_api_headers(),
                    json=invoice_data,
                    timeout=30
                )

                frappe.logger().debug(f"Fiscal Device Response Status: {response.status_code}")
                frappe.logger().debug(f"Fiscal Device Response Text: {response.text}")

                if response.status_code == 200:
                    return response.json()
                else:
                    error_message = response.json().get('description', response.text)
                    frappe.logger().error(f"Fiscal Device Error: {error_message}")
                    if attempt < retries - 1:
                        frappe.logger().info(f"Retrying fiscalization (attempt {attempt + 2}/{retries})")
                        continue
                    else:
                        frappe.throw(
                            _("Failed to sign invoice after {0} attempts. Last error: {1}").format(retries, error_message)
                        )

            except requests.exceptions.RequestException as e:
                frappe.logger().error(f"Fiscal Device Request Error: {str(e)}")
                if attempt < retries - 1:
                    frappe.logger().info(f"Retrying fiscalization (attempt {attempt + 2}/{retries})")
                    continue
                else:
                    frappe.throw(_("Failed to connect to fiscal device after {0} attempts.").format(retries))
            except Exception as e:
                frappe.logger().error(f"Unexpected Error: {str(e)}")
                frappe.throw(_("Unexpected error during fiscalization: {0}").format(str(e)))

    def format_invoice_data(self, invoice, items, is_inclusive=True):
        """
        Format invoice data for fiscal device
        Args:
            invoice: Sales Invoice document
            items: List of invoice items
            is_inclusive: Whether prices are VAT inclusive
        """
        # Convert posting_date to datetime if it's a string
        if isinstance(invoice.posting_date, str):
            invoice_date = datetime.strptime(invoice.posting_date, "%Y-%m-%d").strftime("%d_%m_%Y")
        else:
            invoice_date = invoice.posting_date.strftime("%d_%m_%Y")

        # Calculate totals with exactly 2 decimal places
        grand_total = "{:.2f}".format(flt(invoice.grand_total, 2))
        net_total = "{:.2f}".format(flt(invoice.net_total, 2))
        tax_total = "{:.2f}".format(flt(invoice.total_taxes_and_charges, 2))
        discount_total = "{:.2f}".format(flt(invoice.discount_amount, 2))

        # Format items list according to documentation
        items_list = []
        for item in items:
            # Get HS code, default to empty if not available
            hscode = item.get('custom_hs_code', '')
            
            # Calculate unit price (unitNetto)
            unit_price = "{:.2f}".format(flt(item.amount / item.qty if item.qty else 0, 2))
            
            # Format quantity and total amount with exactly 2 decimal places
            quantity = "{:.2f}".format(flt(item.qty, 2))
            total_amount = "{:.2f}".format(flt(item.amount, 2))
            
            # Format item string according to documentation
            # Note the space at the start and max length of 512 symbols
            item_string = f" {hscode}{item.item_name} {quantity} {unit_price} {total_amount}"
            if len(item_string) > 512:
                item_string = item_string[:512]
            items_list.append(item_string)

        # Construct payload according to documentation
        payload = {
            "invoice_date": invoice_date,
            "invoice_number": invoice.name,
            "invoice_pin": self.control_unit_pin,
            "customer_pin": invoice.tax_id or "",
            "customer_exid": invoice.custom_tax_exemption_id or "",
            "grand_total": grand_total,
            "net_subtotal": net_total if is_inclusive else "",  # Only for inclusive VAT
            "tax_total": tax_total,
            "net_discount_total": discount_total,
            "sel_currency": invoice.currency,
            "rel_doc_number": invoice.return_against or "",
            "items_list": items_list
        }

        return payload

    def get_vat_rate(self, item):
        """Fetch VAT rate from item tax template"""
        tax_rate = 16  # Default to 16% if not found
        if item.item_tax_template:
            tax_template = frappe.get_doc("Item Tax Template", item.item_tax_template)
            for tax in tax_template.taxes:
                if tax.tax_type == "VAT - SHKL":
                    tax_rate = tax.tax_rate
                    break
        return tax_rate

@frappe.whitelist()
def test_connection(device_ip, port):
    """Test connection to fiscal device with proper payload format"""
    try:
        # Get settings doc for configuration values
        settings = frappe.get_doc("Fiscal Device Settings")
        
        # Construct test URL with the correct endpoint for inclusive VAT
        url = f"http://{device_ip}:{port}/api/sign?invoice+1"
        
        # Create test payload using values from settings
        test_payload = {
            "invoice_date": frappe.utils.today().replace('-', '_'),
            "invoice_number": f"TEST_{frappe.utils.now_datetime().strftime('%H%M%S')}",
            "invoice_pin": settings.control_unit_pin,  # Use PIN from settings
            "customer_pin": "",
            "customer_exid": "",
            "grand_total": "1.00",
            "net_subtotal": "0.86",
            "tax_total": "0.14",
            "net_discount_total": "0.00",
            "sel_currency": "KSH",
            "rel_doc_number": "",
            "items_list": [
                " TEST ITEM 1.00 1.00 1.00"
            ]
        }
        
        # Get headers from settings
        headers = {
            'Content-Type': 'application/json',
            'Authorization': settings.bearer_token
        }
        
        if settings.debug_mode:
            frappe.logger().debug(f"Test Connection URL: {url}")
            frappe.logger().debug(f"Test Payload: {json.dumps(test_payload, indent=2)}")
        
        # Make the API request
        response = requests.post(
            url=url,
            headers=headers,
            json=test_payload,
            timeout=10
        )
        
        if settings.debug_mode:
            frappe.logger().debug(f"Response Status: {response.status_code}")
            frappe.logger().debug(f"Response Text: {response.text}")
        
        if response.status_code == 200:
            response_data = response.json()
            if response_data.get('cu_serial_number'):
                return {
                    'success': True,
                    'message': _('Connected to device {0}').format(response_data.get('cu_serial_number')),
                    'serial_number': response_data.get('cu_serial_number')
                }
            else:
                return {
                    'success': False,
                    'error': _('Invalid response from device: {0}').format(
                        response_data.get('description', 'No description provided')
                    )
                }
        else:
            try:
                error_detail = response.json().get('description', '')
            except:
                error_detail = response.text[:100] if response.text else ''
            
            return {
                'success': False,
                'error': _('Device responded with status code: {0}. Details: {1}').format(
                    response.status_code, error_detail
                )
            }
            
    except requests.exceptions.ConnectionError:
        return {
            'success': False,
            'error': _('Could not connect to device at {0}:{1}. Please check if the device is online.').format(
                device_ip, port
            )
        }
    except requests.exceptions.Timeout:
        return {
            'success': False,
            'error': _('Connection timed out. Please check your network connection.')
        }
    except Exception as e:
        if settings.debug_mode:
            frappe.logger().error(f"Test Connection Error: {str(e)}")
        return {
            'success': False,
            'error': _('Unexpected error: {0}').format(str(e))
        }