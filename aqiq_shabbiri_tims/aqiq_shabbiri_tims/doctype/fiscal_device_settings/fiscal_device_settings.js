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
    if (!frm.doc.device_ip || !frm.doc.port) {
        frm.dashboard.reset();
        frm.dashboard.set_headline(
            `<div class="indicator red">
                ${__('Device IP and Port not configured')}
            </div>`
        );
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
            if (r.message.success) {
                // Store the serial number if provided
                if (r.message.serial_number && !frm.doc.control_unit_serial) {
                    frappe.model.set_value(frm.doctype, frm.docname, 
                        'control_unit_serial', r.message.serial_number);
                    frm.save();
                }
                
                frm.dashboard.set_headline(
                    `<div class="indicator green">
                        ${r.message.message || __('Device Connected')}
                    </div>`
                );
            } else {
                frm.dashboard.set_headline(
                    `<div class="indicator red">
                        ${__('Connection Failed')}: ${r.message.error || __('Could not connect to device')}
                    </div>`
                );
                // Also show as a message for better visibility
                frappe.msgprint({
                    title: __('Connection Failed'),
                    message: r.message.error || __('Could not connect to device'),
                    indicator: 'red'
                });
            }
        }
    });
}