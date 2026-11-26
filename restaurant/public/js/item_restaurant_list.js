// The full-form shortcut exists only while the user navigates Item from the restaurant workspace.
// Outside that flow (Stock, Selling, Hospital...) the native list primary action is left untouched.
(() => {
    const settings = frappe.listview_settings.Item || (frappe.listview_settings.Item = {});
    const hadOwnAction = Object.prototype.hasOwnProperty.call(settings, "primary_action");
    const nativeAction = settings.primary_action;

    function restaurantPrimaryAction() {
        frappe.model.with_doctype("Item", () => {
            const doc = frappe.model.get_new_doc("Item", null, null, true);
            frappe.set_route("Form", "Item", doc.name);
        });
    }

    function syncPrimaryAction() {
        if (frappe.restaurant_item_navigation) {
            settings.primary_action = restaurantPrimaryAction;
        } else if (hadOwnAction) {
            settings.primary_action = nativeAction;
        } else {
            delete settings.primary_action;
        }
    }

    frappe.router.on("change", () => {
        const route = frappe.get_route();
        if (!["List", "Form"].includes(route[0]) || route[1] !== "Item") {
            frappe.restaurant_item_navigation = false;
        }
        syncPrimaryAction();
    });
    syncPrimaryAction();
    frappe.restaurant_item_list = { sync: syncPrimaryAction };
})();
