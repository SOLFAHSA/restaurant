// Copyright (c) 2026, Grintsys and contributors
// For license information, please see license.txt

frappe.ui.form.on("Restaurant Order", {
    refresh(frm) {
        frm.add_custom_button(__("Abrir en Punto de Venta"), () => {
            frappe.route_options = { order_name: frm.doc.name };
            frappe.set_route("restaurant-pos");
        });
        if (frm.doc.sales_invoice) {
            frm.add_custom_button(__("Ver Factura SAR"), () => {
                frappe.set_route("Form", "Sales Invoice", frm.doc.sales_invoice);
            });
        }
    },
});

