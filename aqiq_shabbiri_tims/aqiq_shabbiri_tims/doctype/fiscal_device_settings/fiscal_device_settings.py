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
        if not self.bearer_token:
            self.bearer_token = "Basic ZxZoaZMUQbUJDljA7kTExQ==2023"
            self.save()
        
        return {
            'Content-Type': 'application/json',
            'Authorization': self.bearer_token
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
        try:
            # Convert posting_date to datetime if it's a string
            if isinstance(invoice.posting_date, str):
                invoice_date = datetime.datetime.strptime(invoice.posting_date, "%Y-%m-%d").strftime("%d_%m_%Y")
            else:
                invoice_date = invoice.posting_date.strftime("%d_%m_%Y")

            # Calculate totals with exactly 2 decimal places
            grand_total = "{:.2f}".format(flt(invoice.grand_total, 2))
            net_total = "{:.2f}".format(flt(invoice.net_total, 2))
            tax_total = "{:.2f}".format(flt(invoice.total_taxes_and_charges or 0, 2))
            discount_total = "{:.2f}".format(flt(invoice.discount_amount or 0, 2))

            # Format items list according to documentation
            items_list = []
            for item in items:
                # Get HS code, default to empty if not available
                hscode = getattr(item, 'custom_hs_code', '') or ''
                hscode = hscode.strip()
                
                # Calculate unit price and ensure it's not zero
                quantity = flt(item.qty, 2)
                if quantity <= 0:
                    frappe.throw(_("Quantity must be greater than zero for item {0}").format(item.item_name))
                
                unit_price = flt(item.rate, 2)
                if unit_price <= 0:
                    frappe.throw(_("Unit price must be greater than zero for item {0}").format(item.item_name))
                
                # Format the item string with proper spacing
                item_string = " "  # Start with a space as per documentation
                if hscode:
                    item_string += f"{hscode} "
                
                item_string += f"{item.item_name} {quantity:.2f} {unit_price:.2f} {flt(item.amount, 2):.2f}"
                
                if len(item_string) > 512:
                    item_string = item_string[:512]
                items_list.append(item_string)

            if not items_list:
                frappe.throw(_("No items found in invoice"))

            # Handle customer PIN - must be valid format if provided
            customer_pin = ""
            if invoice.tax_id:
                customer_pin = ''.join(filter(str.isalnum, invoice.tax_id.upper()))
                if customer_pin and not customer_pin.startswith('P'):
                    frappe.throw(_("Customer PIN must start with 'P' if provided"))

            # Construct payload according to documentation
            payload = {
                "invoice_date": invoice_date,
                "invoice_number": invoice.name,
                "invoice_pin": self.control_unit_pin,
                "customer_pin": customer_pin,
                "customer_exid": (invoice.get('custom_tax_exemption_id') or "").strip(),
                "grand_total": grand_total,
                "net_subtotal": net_total if is_inclusive else "",
                "tax_total": tax_total,
                "net_discount_total": discount_total,
                "sel_currency": "KSH",
                "rel_doc_number": invoice.return_against or "",
                "items_list": items_list
            }

            # Validate mandatory fields
            if not self.control_unit_pin:
                frappe.throw(_("Control Unit PIN is mandatory"))
            if not payload["invoice_date"]:
                frappe.throw(_("Invoice date is mandatory"))
            if not payload["invoice_number"]:
                frappe.throw(_("Invoice number is mandatory"))

            return payload

        except Exception as e:
            frappe.log_error(
                message=f"Error formatting invoice data: {str(e)}\nPayload: {locals().get('payload', 'N/A')}",
                title="Fiscal Device Format Error"
            )
            raise

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
    try:
        # Construct test URL - using the inclusive VAT endpoint
        url = f"http://{device_ip}:{port}/api/sign?invoice+1"
        
        # Create a test payload matching the documentation example
        test_payload = {
            "invoice_date": frappe.utils.today().replace('-', '_'),
            "invoice_number": f"TEST_{frappe.utils.now_datetime().strftime('%H%M%S')}",
            "invoice_pin": "P051201909L",
            "customer_pin": "",
            "customer_exid": "",
            "grand_total": "1.00",
            "net_subtotal": "0.86",
            "tax_total": "0.14",
            "net_discount_total": "0.00",
            "sel_currency": "KSH",
            "rel_doc_number": "",
            "items_list": [
                " TEST ITEM 1.00 1.00 1.00"  # Note the space at the start
            ]
        }
        
        # Get settings doc for headers
        settings = frappe.get_doc("Fiscal Device Settings")
        
        # Make the API request
        response = requests.post(
            url=url,
            headers=settings.get_api_headers(),
            json=test_payload,
            timeout=10
        )
        
        # Check response
        if response.status_code == 200:
            response_data = response.json()
            if response_data.get('cu_serial_number'):
                
                # Update the settings document with actual device details
                # settings.db_set('control_unit_serial', response_data.get('cu_serial_number'))
                
                # Extract the actual device PIN from the successful response if available
                # if response_data.get('invoice_pin'):
                #     settings.db_set('control_unit_pin', response_data.get('invoice_pin'))
                
                # Commit the transaction
                # frappe.db.commit()
                
                return {
                    'success': True,
                    'message': _('Connected to device {0}').format(response_data.get('cu_serial_number')),
                    'serial_number': response_data.get('cu_serial_number')
                }
            else:
                return {
                    'success': False,
                    'error': _('Invalid response from device: {0}').format(response_data.get('description', 'No description'))
                }
        else:
            # Try to get error message from response
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
            'error': _('Could not connect to device at {0}:{1}').format(device_ip, port)
        }
    except requests.exceptions.Timeout:
        return {
            'success': False,
            'error': _('Connection timed out')
        }
    except json.JSONDecodeError:
        return {
            'success': False,
            'error': _('Invalid JSON response from device')
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }