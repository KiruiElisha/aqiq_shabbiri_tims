# Copyright (c) 2024, Ronoh and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
import requests
from requests.exceptions import RequestException
import json
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
            'Authorization': 'Basic ZxZoaZMUQbUJDljA7kTExQ==2023'
        }

    def throw_error(self, message, details=None):
        """Throw error with optional debug details"""
        if self.debug_mode and details:
            full_message = f"{message}\n\nDebug Details:\n{details}"
            frappe.throw(_(full_message))
        else:
            frappe.throw(_(message))

    def sign_invoice(self, invoice_data, is_inclusive=True):
        """
        Sign an invoice with the fiscal device
        Args:
            invoice_data (dict): Invoice data to be signed
            is_inclusive (bool): Whether prices are VAT inclusive
        """
        if not self.enable_device:
            self.throw_error(_("Fiscal Device is not enabled"))

        if not self.device_ip or not self.port:
            self.throw_error(_("Device IP and Port must be configured"))

        # Determine endpoint based on VAT inclusion
        endpoint = "invoice+1" if is_inclusive else "invoice+2"
        url = f"http://{self.device_ip}:{self.port}/api/sign?{endpoint}"

        # Log the request payload for debugging
        frappe.logger().debug(f"Fiscal Device Request URL: {url}")
        frappe.logger().debug(f"Fiscal Device Request Payload: {invoice_data}")

        try:
            response = requests.post(
                url=url,
                headers=self.get_api_headers(),
                json=invoice_data,
                timeout=30
            )

            # Log the raw response
            frappe.logger().debug(f"Fiscal Device Response Status: {response.status_code}")
            frappe.logger().debug(f"Fiscal Device Response Text: {response.text}")

            if response.status_code == 200:
                return response.json()
            else:
                error_message = ""
                try:
                    # Try to parse JSON response
                    error_data = response.json()
                    error_message = error_data.get('description', '')
                except:
                    # If JSON parsing fails, get raw text
                    error_message = response.text

                # Log the error details
                frappe.logger().error(f"""
                    Fiscal Device Error:
                    Status Code: {response.status_code}
                    URL: {url}
                    Headers: {self.get_api_headers()}
                    Payload: {invoice_data}
                    Response: {error_message}
                """)

                self.throw_error(
                    _("Failed to sign invoice. Status Code: {0}. Details: {1}").format(
                        response.status_code, error_message or "No error details available"
                    ),
                    f"""
                    URL: {url}
                    Payload: {invoice_data}
                    Response: {error_message}
                    """
                )

        except requests.exceptions.ConnectionError as e:
            frappe.logger().error(f"Fiscal Device Connection Error: {str(e)}")
            self.throw_error(_("Connection error: Could not connect to fiscal device"))
        except requests.exceptions.Timeout as e:
            frappe.logger().error(f"Fiscal Device Timeout Error: {str(e)}")
            self.throw_error(_("Connection timeout: Fiscal device took too long to respond"))
        except Exception as e:
            frappe.logger().error(f"Fiscal Device Unexpected Error: {str(e)}")
            self.throw_error(_("Error signing invoice: {0}").format(str(e)))

    def format_invoice_data(self, invoice, items, is_inclusive=True):
        """
        Format invoice data for fiscal device
        Args:
            invoice: Sales Invoice document
            items: List of invoice items
            is_inclusive: Whether prices are VAT inclusive
        """
        # Format date as required (DD_MM_YYYY)
        invoice_date = invoice.posting_date.strftime("%d_%m_%Y")

        # Calculate totals - ensure 2 decimal places
        grand_total = "{:.2f}".format(flt(invoice.grand_total, 2))
        net_total = "{:.2f}".format(flt(invoice.net_total, 2))
        tax_total = "{:.2f}".format(flt(invoice.total_taxes_and_charges, 2))
        discount_total = "{:.2f}".format(flt(invoice.discount_amount, 2))

        # Base payload
        payload = {
            "invoice_date": invoice_date,
            "invoice_number": invoice.name,
            "invoice_pin": self.control_unit_pin,  # Mandatory field
            "customer_pin": invoice.tax_id or "",
            "customer_exid": invoice.custom_tax_exemption_id or "",
            "grand_total": grand_total,
            "net_subtotal": net_total if is_inclusive else "",
            "tax_total": tax_total,
            "net_discount_total": discount_total,
            "sel_currency": "KSH",
            "rel_doc_number": invoice.return_against or ""
        }

        # Format items based on VAT inclusion
        if is_inclusive:
            # Use items_array for inclusive VAT
            items_array = []
            for item in items:
                items_array.append({
                    "name": item.item_name,
                    "hscode": item.get('hscode', ''),
                    "brut_price": "{:.2f}".format(flt(item.amount, 2)),
                    "quantity": "{:.2f}".format(flt(item.qty, 2))
                })
            payload["items_array"] = items_array
        else:
            # Use items_list for exclusive VAT
            items_list = []
            for item in items:
                qty = "{:.2f}".format(flt(item.qty, 2))
                rate = "{:.2f}".format(flt(item.rate, 2))
                amount = "{:.2f}".format(flt(item.amount, 2))
                hscode = item.get('hscode', '')
                
                # Format: "{hscode}{Description} {quantity} {unitNetto} {sumAmount}"
                item_str = f"{hscode}{item.item_name} {qty} {rate} {amount}"
                items_list.append(item_str[:512])
            payload["items_list"] = items_list

        return payload

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
                settings.db_set('control_unit_serial', response_data.get('cu_serial_number'))
                
                # Extract the actual device PIN from the successful response if available
                if response_data.get('invoice_pin'):
                    settings.db_set('control_unit_pin', response_data.get('invoice_pin'))
                
                # Commit the transaction
                frappe.db.commit()
                
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