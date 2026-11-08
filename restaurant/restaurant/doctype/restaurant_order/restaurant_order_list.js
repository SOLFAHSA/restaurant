// Copyright (c) 2026, Grintsys and contributors
// For license information, please see license.txt

frappe.listview_settings["Restaurant Order"] = {
    hide_name_column: false,
    add_fields: ["status", "grand_total", "sales_invoice", "pos_opening_shift", "pos_profile", "restaurant_table", "waiter_name", "customer_name"],

    get_indicator(doc) {
        const status = doc.status || "En curso";
        if (status === "Facturada") {
            return [__("Facturada"), "green", "status,=,Facturada"];
        } else if (status === "Cancelada") {
            return [__("Cancelada"), "red", "status,=,Cancelada"];
        }
        return [__("En curso"), "blue", "status,=,En curso"];
    },

    onload(listview) {
        listview.page.add_inner_button(
            __("Punto de Venta"),
            () => {
                frappe.set_route("restaurant-pos");
            },
            __("Acciones")
        );

        listview.page.set_primary_action(__("Nueva cuenta"), () => {
            frappe.set_route("restaurant-pos");
        });
    },
};

