// The native form remains available for import, permissions, and maintenance.
frappe.ui.form.on("Restaurant Area", {
    setup(frm) {
        frm.set_query("waiter", () => ({
            filters: { status: "Active", designation: "Mesero", branch: frm.doc.branch },
        }));
    },
    refresh(frm) {
        frm.add_custom_button(__("Abrir diseño de áreas"), () => {
            frappe.set_route("restaurant-location", frm.is_new() ? "new" : frm.doc.name);
        });
    },
    branch(frm) {
        frm.set_value("waiter", null);
    },
});
