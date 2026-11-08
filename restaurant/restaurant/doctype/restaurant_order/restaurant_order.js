// Copyright (c) 2026, Grintsys and contributors
// For license information, please see license.txt

frappe.ui.form.on("Restaurant Order", {
    refresh(frm) {
        const status = frm.doc.status || "En curso";
        const indicatorColor = status === "Facturada" ? "green" : (status === "Cancelada" ? "red" : "blue");
        frm.page.set_indicator(__(status), indicatorColor);

        // Acciones principales inspiradas en Odoo POS Órdenes
        frm.add_custom_button(__("Abrir en Punto de Venta"), () => {
            frappe.route_options = { order_name: frm.doc.name };
            frappe.set_route("restaurant-pos");
        }).addClass("btn-primary");

        if (frm.doc.sales_invoice) {
            frm.add_custom_button(__("Ver Factura SAR"), () => {
                frappe.set_route("Form", "Sales Invoice", frm.doc.sales_invoice);
            }, __("Facturación"));
        }

        if (!frm.is_new()) {
            frm.add_custom_button(__("Imprimir Comanda / Precuenta"), () => {
                frappe.utils.print(frm.doc.doctype, frm.doc.name);
            }, __("Impresión"));
        }

        if (status === "En curso" && !frm.is_new()) {
            frm.add_custom_button(__("Cancelar orden"), () => {
                frappe.confirm(
                    __("¿Estás seguro de cancelar esta orden? La mesa asignada se liberará automáticamente."),
                    () => {
                        frappe.call({
                            method: "restaurant.pos.cancel_pos_order",
                            args: { order_name: frm.doc.name },
                            freeze: true,
                            freeze_message: __("Cancelando orden y liberando mesa..."),
                            callback(r) {
                                if (!r.exc) {
                                    frappe.show_alert({
                                        message: __("Orden cancelada con éxito"),
                                        indicator: "green",
                                    });
                                    frm.reload_doc();
                                }
                            },
                        });
                    }
                );
            }, __("Acciones"));
        }
    },
});
