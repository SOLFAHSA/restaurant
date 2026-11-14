// Copyright (c) 2026, Grintsys and contributors
// For license information, please see license.txt

frappe.listview_settings["Restaurant Order"] = {
    hide_name_column: true,
    add_fields: [
        "status",
        "grand_total",
        "sales_invoice",
        "pos_opening_shift",
        "pos_profile",
        "restaurant_table",
        "table_label",
        "waiter_name",
        "customer_name",
    ],

    get_indicator(doc) {
        const status = doc.status || "En curso";
        if (status === "Facturada") {
            return [__("Facturada"), "green", "status,=,Facturada"];
        }
        if (status === "Cancelada") {
            return [__("Cancelada"), "red", "status,=,Cancelada"];
        }
        return [__("En curso"), "blue", "status,=,En curso"];
    },

    formatters: {
        table_label(value) {
            if (!value) {
                return `<span style="color:#94a3b8;">—</span>`;
            }
            const label = String(value).toLowerCase().startsWith("mesa") ? value : `Mesa ${value}`;
            const safe = frappe.utils.escape_html(label);
            return `<span title="${safe}" style="font-weight:600;color:#002456;">${safe}</span>`;
        },
        customer_name(value) {
            if (!value) return "";
            const safe = frappe.utils.escape_html(value);
            return `<span title="${safe}">${safe}</span>`;
        },
        waiter_name(value) {
            if (!value) return `<span style="color:#94a3b8;">—</span>`;
            const safe = frappe.utils.escape_html(value);
            return `<span title="${safe}">${safe}</span>`;
        },
    },

    onload(listview) {
        listview.page.add_inner_button(
            __("Punto de Venta"),
            () => {
                frappe.set_route("restaurant-pos");
            },
            __("Acciones")
        );

        const primaryBtn = listview.page.set_primary_action(__("Nueva cuenta"), () => {
            frappe.set_route("restaurant-pos");
        });
        if (primaryBtn) {
            primaryBtn.addClass("btn-primary");
        }
    },
};
