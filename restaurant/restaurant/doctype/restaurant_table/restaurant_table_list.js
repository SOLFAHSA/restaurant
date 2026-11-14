// Copyright (c) 2026, Grintsys and contributors
// For license information, please see license.txt

const SHAPE_STYLE_MAP = {
    "Cuadrada": { bg: "#eff6ff", color: "#1d4ed8", border: "#bfdbfe" },
    "Rectangular": { bg: "#eef2ff", color: "#4338ca", border: "#c7d2fe" },
    "Redonda": { bg: "#ecfeff", color: "#0e7490", border: "#a5f3fc" },
    "Ovalada": { bg: "#f0fdfa", color: "#0f766e", border: "#99f6e4" },
    "Cancha azul": { bg: "#dbeafe", color: "#002456", border: "#93c5fd" },
    "Cancha fútbol": { bg: "#effbe9", color: "#2f8500", border: "#a4ce87" },
    "Cancha básquetbol": { bg: "#fff7ed", color: "#c2410c", border: "#fed7aa" },
};

frappe.listview_settings["Restaurant Table"] = {
    hide_name_column: true,
    add_fields: ["status", "shape", "table_number", "restaurant_area", "branch", "seats"],

    get_indicator(doc) {
        const status = doc.status || "Disponible";
        if (status === "Disponible") {
            return [__("Disponible"), "green", "status,=,Disponible"];
        }
        if (status === "Ocupada") {
            return [__("Ocupada"), "red", "status,=,Ocupada"];
        }
        if (status === "Reservada") {
            return [__("Reservada"), "orange", "status,=,Reservada"];
        }
        return [__(status), "grey", `status,=,${status}`];
    },

    formatters: {
        shape(value) {
            if (!value) return "";
            const st = SHAPE_STYLE_MAP[value] || { bg: "#f1f5f9", color: "#334155", border: "#cbd5e1" };
            const safeVal = frappe.utils.escape_html(value);
            return `<span title="${safeVal}" style="display:inline-block;padding:2px 8px;border-radius:999px;font-size:11.5px;font-weight:600;background:${st.bg};color:${st.color};border:1px solid ${st.border};white-space:nowrap;">${safeVal}</span>`;
        },
    },
};

