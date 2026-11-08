frappe.ui.form.on("Restaurant Preparation Display", {
    refresh(frm) {
        if (!frm.is_new()) {
            frm.add_custom_button(__("Abrir monitor de cocina"), () => {
                frappe.route_options = { display: frm.doc.name, view: "preparation" };
                frappe.set_route("restaurant-kds");
            });
        }
    },
});
