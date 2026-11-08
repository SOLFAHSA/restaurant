frappe.ui.form.on("Restaurant Preparation Stage", {
    refresh(frm) {
        if (!frm.is_new()) {
            frm.add_custom_button(__("Pantallas de preparación"), () => {
                frappe.set_route("List", "Restaurant Preparation Display");
            });
        }
    },
});
