// Coexistence check: the Item list keeps the native "Add Item" primary action outside the restaurant flow.
// Run: node apps/restaurant/restaurant/tests/js/item_list_coexistence.test.cjs
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const assert = require("node:assert/strict");

const source = fs.readFileSync(path.join(__dirname, "../../public/js/item_restaurant_list.js"), "utf8");

function loadWith(settings) {
    const listeners = [];
    const state = { route: ["Workspaces", "Stock"], routed: null };
    const frappe = {
        listview_settings: settings ? { Item: settings } : {},
        restaurant_item_navigation: false,
        router: { on: (event, callback) => event === "change" && listeners.push(callback) },
        get_route: () => state.route,
        set_route: (...route) => { state.routed = route; },
        model: { with_doctype: (_doctype, callback) => callback(), get_new_doc: () => ({ name: "new-item-1" }) },
    };
    vm.runInNewContext(source, { frappe });
    const navigate = (...route) => { state.route = route; listeners.forEach(callback => callback()); };
    return { frappe, navigate, state };
}

// Mirrors Frappe ListView.set_primary_action: settings.primary_action wins, otherwise make_new_doc().
function clickPrimary(frappe) {
    const settings = frappe.listview_settings.Item;
    if (settings.primary_action) {
        settings.primary_action();
        return "restaurant";
    }
    return "native";
}

const results = [];
function check(name, fn) {
    fn();
    results.push(name);
}

check("Item list from Stock/Selling/Hospital keeps the native action", () => {
    const { frappe, navigate } = loadWith();
    navigate("List", "Item", "List");
    assert.equal(clickPrimary(frappe), "native");
    assert.equal(Object.prototype.hasOwnProperty.call(frappe.listview_settings.Item, "primary_action"), false);
});

check("Restaurant workspace navigation opens the full Item form", () => {
    const { frappe, navigate, state } = loadWith();
    frappe.restaurant_item_navigation = true;
    navigate("List", "Item", "List");
    assert.equal(clickPrimary(frappe), "restaurant");
    assert.deepEqual(state.routed, ["Form", "Item", "new-item-1"]);
});

check("Leaving the restaurant flow restores the native action", () => {
    const { frappe, navigate } = loadWith();
    frappe.restaurant_item_navigation = true;
    navigate("List", "Item", "List");
    navigate("Workspaces", "Stock");
    assert.equal(frappe.restaurant_item_navigation, false);
    navigate("List", "Item", "List");
    assert.equal(clickPrimary(frappe), "native");
});

check("A primary action defined by another app is preserved", () => {
    let calls = 0;
    const other = { primary_action: () => { calls += 1; } };
    const { frappe, navigate } = loadWith(other);
    navigate("List", "Item", "List");
    frappe.listview_settings.Item.primary_action();
    assert.equal(calls, 1);
    frappe.restaurant_item_navigation = true;
    navigate("List", "Item", "List");
    navigate("Workspaces", "Selling");
    frappe.listview_settings.Item.primary_action();
    assert.equal(calls, 2);
});

console.log(`OK ${results.length} item list coexistence checks`);
results.forEach(name => console.log(`  ✓ ${name}`));
