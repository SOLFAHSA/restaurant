const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../restaurant/page/restaurant_pos/restaurant_pos.js"), "utf8");

function setup(canInvoice = true) {
    const serverOrders = Object.fromEntries(["ORDER-A", "ORDER-B"].map(name => [name, {
        name,
        order_name: name,
        modified: "2026-11-18 20:20:00.000000",
        items: [{ item_name: "Agua", qty: 1, amount: 10 }],
    }]));
    const saves = [];
    const conflicts = [];
    let revision = 0;
    const buttons = new Map();
    const changeOnServer = name => {
        serverOrders[name].modified = "2026-11-18 20:20:00." + String(++revision).padStart(6, "0");
    };
    const frappe = {
        pages: { "restaurant-pos": {} },
        show_alert() {},
        utils: { escape_html: value => String(value) },
        async call({ method, args }) {
            if (method === "restaurant.pos.get_precuenta_data") {
                changeOnServer(args.order_name);
                return { message: { order: structuredClone(serverOrders[args.order_name]) } };
            }
            assert.equal(method, "restaurant.pos.save_pos_order");
            const { name, modified } = args.order;
            if (modified !== serverOrders[name].modified) {
                conflicts.push({ name, modified });
                throw new Error("Stale order");
            }
            saves.push({ name, modified });
            changeOnServer(name);
            return { message: { order: structuredClone(serverOrders[name]) } };
        },
    };

    const POS = vm.runInNewContext(source + "\nLeafRestaurantPOS;", { frappe });
    const pos = Object.assign(Object.create(POS.prototype), {
        currentOrder: structuredClone(serverOrders["ORDER-A"]),
        bootstrap: { orders: Object.values(serverOrders).map(order => structuredClone(order)) },
        canInvoice: () => canInvoice,
        closeSplitView() {},
        createModal(_title, _body, footer) {
            return {
                querySelector(selector) {
                    if (!footer.includes(selector.slice(1, -1))) return null;
                    return { addEventListener(_event, callback) { buttons.set(selector, callback); } };
                },
                remove() {},
            };
        },
        recalculateLocalTotals() {},
        render() {},
    });
    return { pos, saves, conflicts, buttons, changeOnServer, serverOrders };
}

test("precuenta keeps Caja and the order list current so payment can open directly", async () => {
    const { pos, saves, buttons, serverOrders } = setup();
    await pos.openPrecuentaModal();

    const expected = serverOrders["ORDER-A"].modified;
    assert.equal(pos.currentOrder.modified, expected);
    assert.equal(pos.bootstrap.orders[0].modified, expected);
    await buttons.get("[data-precuenta-pay]")();
    assert.deepEqual(saves.at(-1), { name: "ORDER-A", modified: expected });
    assert.equal(pos.paymentScreenState.step, "pay");
});

test("precuenta opened from Órdenes sends its own order to payment", async () => {
    const { pos, saves, buttons, serverOrders } = setup();
    await pos.openPrecuentaModal("ORDER-B");
    assert.equal(pos.currentOrder.name, "ORDER-A");
    const expected = serverOrders["ORDER-B"].modified;

    await buttons.get("[data-precuenta-pay]")();
    assert.equal(pos.currentOrder.name, "ORDER-B");
    assert.deepEqual(saves, [{ name: "ORDER-B", modified: expected }]);
    assert.equal(pos.paymentScreenState.step, "pay");
});

test("waiters can open precuenta without payment permission and real version conflicts still stop a save", async () => {
    const { pos, conflicts, buttons, changeOnServer, serverOrders } = setup(false);
    await pos.openPrecuentaModal();
    assert(buttons.has("[data-precuenta-print]"));
    assert(!buttons.has("[data-precuenta-pay]"));
    const expected = serverOrders["ORDER-A"].modified;
    assert.equal(pos.currentOrder.modified, expected);

    changeOnServer("ORDER-A");
    assert.equal(await pos.persistCurrentOrderSilently(), false);
    assert.deepEqual(conflicts, [{ name: "ORDER-A", modified: expected }]);
});


test("checkout asks for supervisor approval only when the server requests it", async () => {
    const args = { order_name: "ORDER-A", global_discount_percentage: 20, payments: [] };
    const frappe = {
        pages: { "restaurant-pos": {} },
        async call(request) {
            assert.equal(request.method, "restaurant.pos.pay_and_invoice_order");
            assert.equal(request.args, args);
            throw { responseJSON: { exc_type: "DiscountApprovalRequired" } };
        },
    };
    const POS = vm.runInNewContext(source + "\nLeafRestaurantPOS;", { frappe });
    const pos = Object.create(POS.prototype);
    pos.requiresSupervisorAuth = () => false;
    pos.requestSupervisorAuthModal = async (action, method, sameArgs, options) => {
        assert.equal(action, "Descuento sobre el límite");
        assert.equal(method, "restaurant.pos.pay_and_invoice_order");
        assert.equal(sameArgs, args);
        assert.equal(options.requirePin, false);
        return { invoice: { name: "QA" } };
    };
    assert.equal((await pos.submitCheckout(args)).message.invoice.name, "QA");

    pos.requestSupervisorAuthModal = async () => null;
    assert.equal(await pos.submitCheckout(args), null);
});
