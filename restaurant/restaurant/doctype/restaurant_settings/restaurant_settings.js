frappe.ui.form.on("Restaurant Settings", {
    refresh(frm) {
        frm.add_custom_button(__("Ir al Punto de Venta"), () => {
            frappe.set_route("restaurant-pos");
        }).addClass("btn-primary");

        if (!frm.doc.pos_profile) {
            frappe.db.get_list("POS Profile", { filters: { disabled: 0 }, fields: ["name"], limit: 1 }).then(res => {
                if (res && res.length) {
                    frm.set_value("pos_profile", res[0].name);
                } else if (!(frm.doc.payment_methods || []).length) {
                    syncProfileSettings(frm, null);
                }
            });
        } else if (!(frm.doc.payment_methods || []).length) {
            syncProfileSettings(frm, frm.doc.pos_profile, true);
        }
    },

    pos_profile(frm) {
        if (frm._loading_profile) return;
        syncProfileSettings(frm, frm.doc.pos_profile, false);
    },

    enable_self_order(frm) {
        if (!frm.doc.enable_self_order) {
            frm.set_value("enable_mobile_self_order", 0);
            frm.set_value("enable_kiosk_self_order", 0);
        } else {
            syncChannelFlags(frm);
        }
    },

    self_order_channels(frm) {
        syncChannelFlags(frm);
    }
});

function syncChannelFlags(frm) {
    if (!frm.doc.enable_self_order) return;
    const ch = frm.doc.self_order_channels || "Ambos canales";
    if (ch === "Autopedido por celular") {
        frm.set_value("enable_mobile_self_order", 1);
        frm.set_value("enable_kiosk_self_order", 0);
    } else if (ch === "Autopedido por kiosco") {
        frm.set_value("enable_mobile_self_order", 0);
        frm.set_value("enable_kiosk_self_order", 1);
    } else {
        frm.set_value("enable_mobile_self_order", 1);
        frm.set_value("enable_kiosk_self_order", 1);
    }
}

function syncProfileSettings(frm, posProfile, onlyPayments) {
    frm._loading_profile = true;
    frappe.call({
        method: "restaurant.restaurant.doctype.restaurant_settings.restaurant_settings.load_profile_settings",
        args: { pos_profile: posProfile || "" },
        callback(r) {
            frm._loading_profile = false;
            const data = r.message || {};
            if (Array.isArray(data.profile_payments)) {
                frm.clear_table("payment_methods");
                data.profile_payments.forEach(p => {
                    const row = frm.add_child("payment_methods");
                    row.mode_of_payment = p.mode_of_payment;
                    row.enabled = p.enabled;
                    row.is_default = p.is_default;
                });
                frm.refresh_field("payment_methods");
            }
            if (!onlyPayments && data.config && Object.keys(data.config).length) {
                const cfg = data.config;
                const scalarFields = [
                    "default_preset", "enable_self_order", "self_order_channels",
                    "enable_mobile_self_order", "enable_kiosk_self_order",
                    "auto_validate_orders", "tips_enabled", "enable_rounded_total",
                    "show_product_images", "show_category_images", "group_by_category",
                    "large_scrollbars", "share_open_orders", "restrict_categories",
                    "allow_category_search", "allow_line_discount", "price_display_mode",
                    "allow_global_discount", "enable_promotions_coupons",
                    "enable_gift_cards", "enable_loyalty_program",
                    "allow_whatsapp_invoice", "allow_email_invoice", "enable_self_invoicing"
                ];
                scalarFields.forEach(f => {
                    if (cfg[f] !== undefined && frm.fields_dict[f]) {
                        frm.set_value(f, cfg[f]);
                    }
                });
                if (Array.isArray(cfg.allowed_categories)) {
                    frm.clear_table("allowed_categories");
                    cfg.allowed_categories.forEach(cat => {
                        const row = frm.add_child("allowed_categories");
                        row.item_group = cat;
                    });
                    frm.refresh_field("allowed_categories");
                }
            }
        }
    });
}
