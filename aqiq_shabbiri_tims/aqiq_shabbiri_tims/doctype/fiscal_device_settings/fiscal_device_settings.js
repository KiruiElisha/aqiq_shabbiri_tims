// Copyright (c) 2024, Ronoh and contributors
// For license information, please see license.txt

frappe.ui.form.on('Fiscal Device Settings', {
    refresh: function(frm) {
        // Add test connection button
        frm.add_custom_button(__('Test Connection'), function() {
            test_device_connection(frm);
        }, __('Device Operations'));
    }
});

function test_device_connection(frm) {
    // Validate required fields
    if (!frm.doc.device_ip || !frm.doc.port) {
        frm.dashboard.reset();
        frm.dashboard.set_headline(
            `<div class="indicator red">
                ${__('Device IP and Port not configured')}
            </div>`
        );
        frappe.msgprint({
            title: __('Configuration Required'),
            message: __('Please configure Device IP and Port before testing connection'),
            indicator: 'red'
        });
        return;
    }
    
    // Show testing status
    frm.dashboard.set_headline(
        `<div class="indicator blue">
            ${__('Testing connection to fiscal device...')}
        </div>`
    );
    
    frappe.call({
        method: 'aqiq_shabbiri_tims.aqiq_shabbiri_tims.doctype.fiscal_device_settings.fiscal_device_settings.test_connection',
        args: {
            'device_ip': frm.doc.device_ip,
            'port': frm.doc.port
        },
        callback: function(r) {
            frm.dashboard.reset();
            if (r.message && r.message.success) {
                frm.dashboard.set_headline(
                    `<div class="indicator green">
                        ${r.message.message || __('Device Connected')}
                    </div>`
                );
                
                frappe.show_alert({
                    message: __('Connection test successful'),
                    indicator: 'green'
                }, 5);
            } else {
                const error_msg = r.message ? r.message.error : __('Could not connect to device');
                frm.dashboard.set_headline(
                    `<div class="indicator red">
                        ${__('Connection Failed')}: ${error_msg}
                    </div>`
                );
                
                frappe.msgprint({
                    title: __('Connection Failed'),
                    message: error_msg,
                    indicator: 'red'
                });
            }
        },
        error: function(r) {
            frm.dashboard.reset();
            frm.dashboard.set_headline(
                `<div class="indicator red">
                    ${__('Connection Error')}
                </div>`
            );
            
            frappe.msgprint({
                title: __('Connection Error'),
                message: __('An error occurred while testing the connection'),
                indicator: 'red'
            });
        }
    });
}