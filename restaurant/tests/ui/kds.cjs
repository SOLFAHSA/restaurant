// Browser coverage uses real configuration reads and isolated response fixtures.
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const { chromium } = require(process.env.LEAF_PLAYWRIGHT_MODULE || "playwright");

(async () => {
    assert(process.env.LEAF_UI_USER && process.env.LEAF_UI_PASSWORD, "Development login is required");
    const output = process.env.LEAF_UI_OUTPUT || "/tmp/kds-ui-qa";
    fs.mkdirSync(output, { recursive: true });
    const browser = await chromium.launch({
        headless: true,
        ...(process.env.LEAF_UI_BROWSER ? { executablePath: process.env.LEAF_UI_BROWSER } : {}),
        args: ["--no-sandbox"],
    });
    const context = await browser.newContext({baseURL: process.env.LEAF_UI_BASE_URL || "http://localhost:8000", viewport: {width: 1440, height: 960}});
    try {
        const login = await context.request.post("/api/method/login", {form: {usr: process.env.LEAF_UI_USER, pwd: process.env.LEAF_UI_PASSWORD}});
        assert(login.ok(), "Development login failed");
        const page = await context.newPage();
        const errors = [];
        page.on("pageerror", error => errors.push(error.message));
        await page.goto("/app/restaurant-kds");
        try {
            await page.locator(".rkds-hub-card").first().waitFor({state: "visible"});
        } catch (error) {
            await page.screenshot({path: path.join(output, "error-inicio.png"), fullPage: true});
            console.error("Browser errors:", JSON.stringify(errors));
            throw error;
        }
        await page.screenshot({path: path.join(output, "01-pantallas.png"), fullPage: true});
        await page.locator('[data-kds-action="open-config"]').first().click();
        await page.locator('[data-config-control="display_name"] input').waitFor({state: "visible"});
        assert.equal(await page.locator('[data-config-control="stages"] .tb-selected-value').count(), 3);
        const originalAutoClear = await page.locator('[data-config-control="auto_clear"] input[data-fieldname="auto_clear"]').isChecked();
        await page.locator('[data-config-control="auto_clear"] input[data-fieldname="auto_clear"]').check();
        await page.locator('[data-config-control="auto_clear_minutes"] input').waitFor({state: "visible"});
        await page.screenshot({path: path.join(output, "02-configuracion.png"), fullPage: true});
        // Restore the original checkbox and save unchanged configuration through Desk.
        await page.locator('[data-config-control="auto_clear"] input[data-fieldname="auto_clear"]').setChecked(originalAutoClear);
        await page.locator('[data-kds-action="save-display"]').click();
        await page.locator(".rkds-hub-card").first().waitFor({state: "visible"});
        await page.locator('[data-kds-action="open-config"]').first().click();
        assert.equal(await page.locator('[data-config-control="auto_clear"] input[data-fieldname="auto_clear"]').isChecked(), originalAutoClear);
        await page.locator('[data-kds-action="open-stages-list"]').click();
        await page.locator('[data-kds-action="new-stage"]').click();
        await page.locator('.modal:visible input[data-fieldname="stage_name"]').waitFor({state: "visible"});
        await page.screenshot({path: path.join(output, "03-etapa.png"), fullPage: true});
        await page.locator(".modal:visible .modal-header .btn-modal-close").click();
        await page.locator('[data-kds-action="open-hub"]').click();

        // Exercise rendering and clicks without writing any real order.
        const fixture = await page.evaluate(() => {
            const monitor = frappe.pages["restaurant-kds"].restaurant_kds;
            return {display: monitor.currentDisplay(), displays: monitor.displays, stages_catalog: monitor.stagesCatalog};
        });
        const stages = fixture.display.stages;
        let index = 0;
        let completed = [];
        let dismissed = false;
        let secondIndex = 1;
        let secondDismissed = false;
        let secondMarks = 0;
        const marks = [];
        await page.route("**/api/method/restaurant.kds.*", async route => {
            const method = new URL(route.request().url()).pathname.split(".").pop();
            if (method === "get_kds_state") {
                const order = {name: "QA-ORDER", ticket_name: "QA-TICKET", order_name: "Mesa 7", table_label: "7", guests: 2, service_type: "Comer en el local", stage_index: index, stages,
                    kds_stage: stages[index].name, completed_item_names: completed, kds_timer_start: "2026-11-06 10:00:00",
                    items: [{name: "QA-LINE-1", idx: 1, qty: 1, item_name: "Hamburguesa", note: "Sin cebolla"}, {name: "QA-LINE-2", idx: 2, qty: 2, item_name: "Papas fritas"}]};
                const second = {...order, ticket_name: "QA-SECOND-TICKET", stage_index: secondIndex, kds_stage: stages[secondIndex].name, completed_item_names: [], batch_index: 2, batch_count: 2, items: [{name: "QA-SECOND-LINE", idx: 3, qty: 1, item_name: "Sopa del día"}]};
                order.batch_index = 1; order.batch_count = 2;
                return route.fulfill({json: {message: {...fixture, selected_display: fixture.display.name, orders: [...(dismissed ? [] : [order]), ...(secondDismissed ? [] : [second])], server_now: "2026-11-06 10:12:00", stations: ["Todas las estaciones"]}}});
            }
            const args = new URLSearchParams(route.request().postData() || "");
            if (args.get("ticket_id") === "QA-SECOND-TICKET") {
                assert.equal(args.get("order_name"), "QA-ORDER");
                if (method === "toggle_item") {
                    assert.equal(args.get("expected_stage"), stages[secondIndex].name);
                    secondMarks++; secondIndex++;
                } else if (method === "dismiss_ticket") secondDismissed = true;
                else throw new Error("Unexpected second-group write: " + method);
                return route.fulfill({json: {message: {}}});
            }
            if (method === "toggle_item") {
                assert.equal(args.get("ticket_id"), "QA-TICKET");
                assert.equal(args.get("expected_stage"), stages[index].name);
                const name = args.get("item_name");
                marks.push({index, name});
                completed = args.get("completed") === "1" ? [...new Set([...completed, name])] : completed.filter(value => value !== name);
                if (completed.length === 2) {index++; completed = [];}
            } else if (method === "dismiss_ticket") {assert.equal(index, 2); dismissed = true;}
            else throw new Error("Unexpected operational write: " + method);
            return route.fulfill({json: {message: {}}});
        });
        await page.locator('[data-kds-action="open-preparation"]').first().click();
        await page.locator('[data-stage="Todas"]').click();
        assert.equal(await page.locator("[data-card-ticket]").count(), 2);
        await page.screenshot({path: path.join(output, "07-grupos-fusionados.png"), fullPage: true});
        await page.locator(`[data-stage="${stages[0].name}"]`).click();
        await page.locator('[data-item-name="QA-LINE-1"]').click();
        await page.locator('[data-item-name="QA-LINE-1"].is-struck').waitFor({state: "visible"});
        await page.screenshot({path: path.join(output, "04-preparacion.png"), fullPage: true});
        await page.locator('[data-item-name="QA-LINE-2"]').click();
        await page.locator(`[data-stage="${stages[1].name}"]`).click();
        await page.locator('[data-item-name="QA-LINE-1"]').waitFor({state: "visible"});
        assert.equal(await page.locator(".rkds-item-row.is-struck").count(), 0);
        await page.locator('[data-item-name="QA-LINE-1"]').click();
        await page.locator('[data-item-name="QA-LINE-1"].is-struck').waitFor({state: "visible"});
        await page.locator('[data-item-name="QA-LINE-2"]').click();
        await page.locator(`[data-stage="${stages[2].name}"]`).click();
        await page.locator('[data-kds-action="close-order"]').waitFor({state: "visible"});
        await page.screenshot({path: path.join(output, "05-completadas.png"), fullPage: true});
        await page.locator('[data-kds-action="close-order"]').click();
        await page.locator(".rkds-empty-state").waitFor({state: "visible"});
        assert.equal(marks.length, 4);
        await page.locator(`[data-stage="${stages[1].name}"]`).click();
        await page.locator('[data-item-name="QA-SECOND-LINE"]').click();
        await page.locator(`[data-stage="${stages[2].name}"]`).click();
        await page.locator('[data-card-ticket="QA-SECOND-TICKET"] [data-kds-action="close-order"]').click();
        await page.locator(".rkds-empty-state").waitFor({state: "visible"});
        assert.equal(secondMarks, 1);
        await page.setViewportSize({width: 390, height: 844});
        await page.locator('[data-kds-action="open-hub"]').click();
        await page.screenshot({path: path.join(output, "06-movil.png"), fullPage: true});
        const card = await page.locator(".rkds-hub-card").first().boundingBox();
        assert(card && card.x >= 0 && card.x + card.width <= 391, "Mobile cards must remain inside the viewport");
        assert.deepEqual(errors, []);
        console.log("VERIFIED: real hub/config/stage form, fixture two-round item marking, completion/dismiss, desktop/mobile. No operational orders modified.");
    } finally {
        await context.request.get("/api/method/logout").catch(() => {});
        await browser.close();
    }
})().catch(error => {console.error(error.stack || error.message); process.exitCode = 1;});
