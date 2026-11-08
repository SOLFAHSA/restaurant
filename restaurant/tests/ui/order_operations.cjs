// Test the real POS interface with isolated order-operation responses.
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const { chromium } = require(process.env.LEAF_PLAYWRIGHT_MODULE || "playwright");

(async () => {
    assert(process.env.LEAF_UI_USER && process.env.LEAF_UI_PASSWORD, "Development login is required");
    const output = process.env.LEAF_UI_OUTPUT || "/tmp/order-operations-qa";
    fs.mkdirSync(output, {recursive: true});
    const browser = await chromium.launch({headless: true, executablePath: process.env.LEAF_UI_BROWSER, args: ["--no-sandbox"]});
    const context = await browser.newContext({baseURL: process.env.LEAF_UI_BASE_URL || "http://localhost:8000", viewport: {width: 1600, height: 1000}});
    try {
        const login = await context.request.post("/api/method/login", {form: {usr: process.env.LEAF_UI_USER, pwd: process.env.LEAF_UI_PASSWORD}});
        assert(login.ok(), "Development login failed");
        const page = await context.newPage();
        const errors = [];
        const calls = [];
        page.on("pageerror", error => errors.push(error.message));
        const initial = {
            name: "QA-SOURCE", order_name: "Manuel Padilla", status: "En curso", service_type: "Comer en el local",
            restaurant_table: "QA-TABLE-1", table_label: "5", guests: 3, customer: "CONSUMIDOR FINAL", customer_name: "Manuel Padilla",
            modified: "2026-11-06 16:00:00.000000", tip_amount: 0, tip_percentage: 0,
            items: [
                {name: "QA-LINE-A", idx: 1, item_code: "QA-BURGER", item_name: "Hamburguesa con queso", qty: 2, base_rate: 100, options_rate: 0, rate: 100, amount: 200, tax_rate: 15, options_summary: "Acompañamiento: papas fritas", note: "Sin cebolla", kds_status: "En preparación"},
                {name: "QA-LINE-B", idx: 2, item_code: "QA-DRINK", item_name: "Refresco", qty: 1, base_rate: 40, options_rate: 0, rate: 40, amount: 40, tax_rate: 15, kds_status: "Listo"},
            ], subtotal: 240, tax_amount: 36, isv_15: 36, isv_18: 0, grand_total: 276,
        };
        let source = structuredClone(initial);
        let target = {...structuredClone(initial), name: "QA-TARGET", order_name: "Ana López", restaurant_table: "QA-TABLE-2", table_label: "7", items: [{...structuredClone(initial.items[1]), name: "QA-TARGET-LINE"}], subtotal: 40, tax_amount: 6, isv_15: 6, grand_total: 46};
        let extraOrders = [];
        let currentId = 0;
        const recalculate = order => {
            order.subtotal = order.items.reduce((sum, row) => sum + row.qty * row.rate, 0);
            order.tax_amount = Number((order.subtotal * 0.15).toFixed(2));
            order.isv_15 = order.tax_amount;
            order.grand_total = order.subtotal + order.tax_amount;
            order.items.forEach(row => {row.amount = row.qty * row.rate;});
            return order;
        };
        const lookup = name => [source, target, ...extraOrders].find(order => order.name === name);
        await page.route("**/api/method/restaurant.pos.*", async route => {
            const method = new URL(route.request().url()).pathname.split(".").pop();
            const params = new URLSearchParams(route.request().postData() || new URL(route.request().url()).search);
            if (method === "get_pos_bootstrap") {
                const response = await route.fetch();
                const payload = await response.json();
                payload.message.orders = [source, target, ...extraOrders];
                payload.message.opening_shift ||= {name: "QA-SHIFT", pos_profile: "Restaurante"};
                return route.fulfill({response, json: payload});
            }
            calls.push({method, args: Object.fromEntries(params)});
            const order = lookup(params.get("order_name"));
            if (method === "save_pos_order") {
                const submitted = JSON.parse(params.get("order"));
                return route.fulfill({json: {message: {order: lookup(submitted.name) || submitted}}});
            }
            if (method === "get_order_operation_context") {
                return route.fulfill({json: {message: {order, orders: [source, target, ...extraOrders].filter(row => row.name !== order.name), tables: [
                    {name: "QA-EMPTY", table_number: "9", area_name: "Terraza", orders: []},
                    {name: "QA-TABLE-2", table_number: "7", area_name: "Salón principal", orders: target.name === order.name ? [] : [target]},
                ]}}});
            }
            if (method === "preview_split_order") {
                const selection = JSON.parse(params.get("split_items"));
                const total = selection.reduce((sum, row) => sum + order.items.find(item => item.name === row.item_name).rate * row.qty * 1.15, 0);
                const all = selection.reduce((sum, row) => sum + row.qty, 0) === order.items.reduce((sum, row) => sum + row.qty, 0);
                return route.fulfill({json: {message: {selected_total: total, original_total: order.grand_total, remaining_total: order.grand_total - total, selected_qty: selection.reduce((sum, row) => sum + row.qty, 0), selected_lines: selection.length, can_split: !all, all_selected: all, rounding_difference: 0}}});
            }
            if (method === "split_order") {
                assert.equal(params.get("expected_modified"), order.modified);
                const selection = new Map(JSON.parse(params.get("split_items")).map(row => [row.item_name, row.qty]));
                const selected = order.items.filter(item => selection.has(item.name)).map(item => ({...item, name: item.name + "-SPLIT" + ++currentId, qty: selection.get(item.name)}));
                order.items = order.items.map(item => ({...item, qty: item.qty - (selection.get(item.name) || 0)})).filter(item => item.qty > 0);
                recalculate(order);
                const created = recalculate({...structuredClone(order), name: "QA-SPLIT-" + currentId, order_name: params.get("new_order_name") || "Cuenta separada", items: selected});
                extraOrders.push(created);
                return route.fulfill({json: {message: {original_order: order, new_order: created}}});
            }
            if (method === "transfer_order_table") {
                assert.equal(params.get("expected_modified"), order.modified);
                if (params.get("target_table")) {
                    order.restaurant_table = params.get("target_table"); order.table_label = "9";
                    return route.fulfill({json: {message: {order, original_order: order, merged: false}}});
                }
                assert.equal(params.get("target_order"), target.name);
                const selectionText = params.get("split_items");
                const selection = selectionText && selectionText !== "null" ? new Map(JSON.parse(selectionText).map(row => [row.item_name, row.qty])) : new Map(order.items.map(item => [item.name, item.qty]));
                target.items.push(...order.items.filter(item => selection.has(item.name)).map(item => ({...item, name: item.name + "-MOVED", qty: selection.get(item.name)})));
                order.items = order.items.map(item => ({...item, qty: item.qty - (selection.get(item.name) || 0)})).filter(item => item.qty > 0);
                if (!order.items.length) order.status = "Cancelada";
                recalculate(order); recalculate(target);
                return route.fulfill({json: {message: {original_order: order, order: target, merged: true}}});
            }
            throw new Error("Unexpected operational request: " + method);
        });
        await page.goto("/app/restaurant-pos");
        await page.locator(".rpos-products-grid").waitFor({state: "visible"});
        const loadSource = async () => page.evaluate(order => frappe.pages["restaurant-pos"].restaurant_pos.loadOrderIntoCaja(order), structuredClone(source));
        const openSplit = async () => {
            await page.locator('[data-action="open-actions-modal"]').click();
            await page.locator('[data-act-tile="split"]').click();
            await page.locator(".rpos-split-view").waitFor({state: "visible"});
        };
        const fractional = {...structuredClone(initial), items: [{...structuredClone(initial.items[0]), qty: 0.001}]};
        const fractionalQty = await page.evaluate(order => {
            const monitor = frappe.pages["restaurant-pos"].restaurant_pos;
            monitor.loadOrderIntoCaja(order);
            return monitor.currentOrder.items[0].qty;
        }, fractional);
        assert.equal(fractionalQty, 0.001, "Loading an account must preserve fractional native quantities");
        await loadSource();
        await page.locator('[data-action="open-actions-modal"]').click();
        await page.screenshot({path: path.join(output, "01-acciones.png"), fullPage: true});
        await page.locator('[data-act-tile="split"]').click();
        await page.locator('[data-action="split-toggle"][data-item-name="QA-LINE-A"]').click();
        await page.locator('[data-action="split-create"]:enabled').waitFor({state: "visible"});
        assert((await page.locator(".rpos-split-amount").innerText()).includes("115"));
        await page.locator("[data-split-account-name]").fill("Compañera Ana");
        await page.screenshot({path: path.join(output, "02-dividir.png"), fullPage: true});
        await page.locator('[data-action="split-create"]').click();
        await page.locator(".rpos-products-grid").waitFor({state: "visible"});
        const newName = await page.evaluate(() => frappe.pages["restaurant-pos"].restaurant_pos.currentOrder.order_name);
        assert.equal(newName, "Compañera Ana");
        assert.equal(calls.filter(call => call.method === "split_order").length, 1);

        source = structuredClone(initial); extraOrders = [];
        await loadSource(); await openSplit();
        await page.locator('[data-action="split-toggle"][data-item-name="QA-LINE-A"]').click();
        await page.locator('[data-action="split-pay"]:enabled').waitFor({state: "visible"});
        await page.locator('[data-action="split-pay"]').click();
        await page.locator("[data-pay-submit]").waitFor({state: "visible"});
        await page.screenshot({path: path.join(output, "03-pago-separado.png"), fullPage: true});
        await page.locator(".rpos-modal-header [data-modal-close]").click();
        assert.equal(calls.filter(call => call.method === "pay_and_invoice_order").length, 0);

        source = structuredClone(initial); extraOrders = [];
        await loadSource(); await openSplit();
        await page.locator('[data-action="split-toggle"][data-item-name="QA-LINE-B"]').click();
        await page.locator('[data-action="split-transfer"]:enabled').waitFor({state: "visible"});
        await page.locator('[data-action="split-transfer"]').click();
        await page.locator('[data-transfer-tab="orders"]').click();
        await page.locator(".rpos-transfer-destination").filter({hasText: "Ana López"}).click();
        await page.screenshot({path: path.join(output, "04-transferir-fusionar.png"), fullPage: true});
        await page.locator("[data-transfer-confirm]").click();
        await page.waitForFunction(() => !frappe.pages["restaurant-pos"].restaurant_pos.operationBusy && !document.querySelector("[data-transfer-confirm]"));
        await page.locator(".rpos-products-grid").waitFor({state: "visible"});
        const transferred = calls.filter(call => call.method === "transfer_order_table").at(-1);
        assert.deepEqual(JSON.parse(transferred.args.split_items), [{item_name: "QA-LINE-B", qty: 1}]);
        assert.equal(calls.filter(call => call.method === "split_order").length, 2, "Selected transfer must be a single atomic transfer request");

        source = structuredClone(initial); extraOrders = [];
        await loadSource(); await openSplit();
        await page.locator('[data-split-quantity="QA-LINE-A"]').fill("2");
        await page.locator('[data-split-quantity="QA-LINE-A"]').press("Tab");
        await page.locator('[data-action="split-toggle"][data-item-name="QA-LINE-B"]').click();
        await page.locator('[data-action="split-pay"]:enabled').waitFor({state: "visible"});
        assert(await page.locator('[data-action="split-create"]').isDisabled());
        await page.locator('[data-action="split-pay"]').click();
        await page.locator("[data-pay-submit]").waitFor({state: "visible"});
        assert.equal(calls.filter(call => call.method === "split_order").length, 2);
        await page.locator(".rpos-modal-header [data-modal-close]").click();
        source = structuredClone(initial); extraOrders = [];
        await loadSource();
        await page.locator('[data-action="open-actions-modal"]').click();
        await page.locator('[data-act-tile="transfer"]').click();
        await page.locator(".rpos-transfer-destination").filter({hasText: "Mesa 9"}).click();
        await page.locator("[data-transfer-confirm]").click();
        await page.waitForFunction(() => !frappe.pages["restaurant-pos"].restaurant_pos.operationBusy && !document.querySelector("[data-transfer-confirm]"));
        await page.locator(".rpos-products-grid").waitFor({state: "visible"});
        assert.equal(await page.evaluate(() => frappe.pages["restaurant-pos"].restaurant_pos.currentOrder.restaurant_table), "QA-EMPTY");
        assert.equal(calls.filter(call => call.method === "transfer_order_table").at(-1).args.target_table, "QA-EMPTY");
        source = structuredClone(initial); extraOrders = [];
        await loadSource();
        await page.locator('[data-action="open-actions-modal"]').click();
        await page.locator('[data-act-tile="transfer"]').click();
        await page.locator('[data-transfer-tab="orders"]').click();
        await page.locator(".rpos-transfer-destination").filter({hasText: "Ana López"}).click();
        await page.locator("[data-transfer-confirm]").click();
        await page.waitForFunction(() => !frappe.pages["restaurant-pos"].restaurant_pos.operationBusy && !document.querySelector("[data-transfer-confirm]"));
        await page.locator(".rpos-products-grid").waitFor({state: "visible"});
        assert.equal(await page.evaluate(() => frappe.pages["restaurant-pos"].restaurant_pos.currentOrder.name), "QA-TARGET");
        source = structuredClone(initial); extraOrders = [];
        await loadSource(); await openSplit();
        await page.setViewportSize({width: 390, height: 844});
        await page.screenshot({path: path.join(output, "05-dividir-movil.png"), fullPage: true});
        const columns = await page.locator(".rpos-split-columns").boundingBox();
        assert(columns && columns.x >= 0 && columns.x + columns.width <= 391);
        assert.deepEqual(errors, []);
        console.log("VERIFIED: actions grid, split selection/name/quote, partial-payment handoff, atomic selected transfer, full-account payment and mobile. Responses isolated; no real orders or payments changed.");
    } finally {
        await context.request.get("/api/method/logout").catch(() => {});
        await browser.close();
    }
})().catch(error => {console.error(error.stack || error.message); process.exitCode = 1;});
