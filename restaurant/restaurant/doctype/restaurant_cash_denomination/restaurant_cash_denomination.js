// Copyright (c) 2026, Grintsys and contributors
// For license information, please see license.txt

frappe.ui.form.on("Restaurant Cash Denomination", {
    refresh(frm) {
        frm.trigger("suggest_label");
    },
    denomination_type(frm) {
        frm.trigger("suggest_label");
    },
    unit_value(frm) {
        frm.trigger("suggest_label");
    },
    currency(frm) {
        frm.trigger("suggest_label");
    },
    suggest_label(frm) {
        if (!frm.is_new() || frm.doc.denomination_label) return;
        const val = flt(frm.doc.unit_value);
        if (val <= 0) return;
        const prefix = frm.doc.denomination_type === "Moneda" ? "Monedas" : "Billetes";
        const symbol = (frm.doc.currency || "HNL") === "HNL" ? "L" : (frm.doc.currency || "");
        const valText = Number.isInteger(val) ? String(val) : val.toFixed(2);
        frm.set_value("denomination_label", `${prefix} ${symbol} ${valText}`.trim());
    },
});

