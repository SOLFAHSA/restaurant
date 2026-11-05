// Keep the full-form shortcut scoped to navigation from the restaurant workspace.
(() => {
    const settings = frappe.listview_settings.Item || (frappe.listview_settings.Item = {});
    const previousAction = settings.primary_action;
    settings.primary_action = function () {
        if (!frappe.restaurant_item_navigation) {
            if (previousAction) return previousAction.apply(this, arguments);
            return frappe.get_list_view().make_new_doc();
        }
        frappe.model.with_doctype("Item", () => {
            const doc = frappe.model.get_new_doc("Item", null, null, true);
            frappe.set_route("Form", "Item", doc.name);
        });
    };
    frappe.router.on("change", () => {
        const route = frappe.get_route();
        if (!["List", "Form"].includes(route[0]) || route[1] !== "Item") {
            frappe.restaurant_item_navigation = false;
        }
    });
})();
