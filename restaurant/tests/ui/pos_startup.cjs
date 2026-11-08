// Read-only browser regression: never opens shifts, saves orders or issues invoices.
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const { chromium } = require(process.env.LEAF_PLAYWRIGHT_MODULE || "playwright");

(async () => {
    assert(process.env.LEAF_UI_USER && process.env.LEAF_UI_PASSWORD, "Explicit development login is required");
    const output = process.env.LEAF_UI_OUTPUT || process.cwd();
    fs.mkdirSync(output, { recursive: true });
    const browser = await chromium.launch({
        headless: true,
        ...(process.env.LEAF_UI_BROWSER ? { executablePath: process.env.LEAF_UI_BROWSER } : {}),
    });
    let context;
    try {
        context = await browser.newContext({
            baseURL: process.env.LEAF_UI_BASE_URL || "http://localhost:8000",
            viewport: { width: 1366, height: 900 },
        });
        const login = await context.request.post("/api/method/login", {
            form: { usr: process.env.LEAF_UI_USER, pwd: process.env.LEAF_UI_PASSWORD },
            timeout: 10000,
        });
        assert(login.ok(), "Development login failed");
        const page = await context.newPage();
        const errors = [];
        const mutations = [];
        page.on("pageerror", error => errors.push(error.message));
        const bootstrapRoute = "**/api/method/restaurant.pos.get_pos_bootstrap";
        await page.route("**/api/method/restaurant.pos.*", async route => {
            if (route.request().url().includes("get_pos_bootstrap")) return route.fallback();
            mutations.push(new URL(route.request().url()).pathname);
            await route.abort();
        });

        // Enter through the actual Workspace card and preserve the existing POS design.
        await page.goto("/app/restaurante");
        await page.locator('[data-action="pos"]').waitFor({ state: "visible" });
        await page.locator('[data-action="pos"]').click();
        await page.waitForURL("**/app/restaurant-pos");
        await page.locator(".rpos-products-grid").waitFor({ state: "visible" });
        const productCount = await page.locator("[data-item-code]").count();
        assert(productCount > 0, "The real native Item catalog must load");
        assert(await page.locator("body").evaluate(node => node.classList.contains("restaurant-theme-context")));
        for (const [tab, selector] of [
            ["Mesas", ".rpos-floor-wrap"], ["Órdenes", ".rpos-orders-view"], ["Caja", ".rpos-products-grid"],
        ]) {
            await page.locator(`[data-nav="${tab}"]`).click();
            await page.locator(selector).waitFor({ state: "visible" });
        }
        await page.screenshot({ path: path.join(output, "pos-restaurante-funcionando.png"), fullPage: true });
        console.log("VERIFIED: Workspace card, real bootstrap, " + productCount + " products and all three tabs.");

        // A broken connection must show a recoverable state, never a blank dark shell.
        await page.route(bootstrapRoute, route => route.abort("failed"));
        await page.reload({ waitUntil: "domcontentloaded" });
        await page.locator("[data-startup-retry]").waitFor({ state: "visible" });
        assert((await page.locator(".rpos-startup").innerText()).includes("No se pudo abrir"));
        await page.screenshot({ path: path.join(output, "pos-error-recuperable.png"), fullPage: true });
        await page.unroute(bootstrapRoute);
        await page.locator("[data-startup-retry]").click();
        await page.locator(".rpos-products-grid").waitFor({ state: "visible" });
        console.log("VERIFIED: failed request and retry recovery.");

        // An incomplete successful response must be rejected before rendering.
        await page.route(bootstrapRoute, route => route.fulfill({ json: { message: {} } }));
        await page.reload({ waitUntil: "domcontentloaded" });
        await page.locator("[data-startup-retry]").waitFor({ state: "visible" });
        await page.unroute(bootstrapRoute);
        await page.locator("[data-startup-retry]").click();
        await page.locator(".rpos-products-grid").waitFor({ state: "visible" });
        console.log("VERIFIED: invalid response is recoverable.");

        // Hold only this browser request; the live server remains available.
        let release;
        await page.route(bootstrapRoute, async route => {
            await new Promise(resolve => { release = resolve; });
            await route.abort().catch(() => {});
        });
        await page.reload({ waitUntil: "domcontentloaded" });
        await page.locator(".rpos-startup[aria-busy=true]").waitFor({ state: "visible" });
        await page.locator("[data-startup-retry]").waitFor({ state: "visible", timeout: 25000 });
        if (release) release();
        await page.unroute(bootstrapRoute);
        await page.locator("[data-startup-retry]").click();
        await page.locator(".rpos-products-grid").waitFor({ state: "visible" });
        console.log("VERIFIED: 20-second timeout and retry recovery.");

        // Simulate no shift only in the response; never modify the real opening.
        await page.route(bootstrapRoute, async route => {
            const response = await route.fetch();
            const data = await response.json();
            data.message.opening_shift = null;
            await route.fulfill({ response, json: data });
        });
        await page.reload({ waitUntil: "domcontentloaded" });
        await page.locator("[data-shift-exit]").waitFor({ state: "visible" });
        await page.locator("[data-shift-exit]").click();
        await page.locator('[data-action="pos"]').waitFor({ state: "visible" });
        assert.equal(await page.locator(".rpos-shell:visible").count(), 0);
        console.log("VERIFIED: no-shift dialog exits to Workspace without opening a shift.");
        assert.deepEqual(mutations, [], "No operational API writes are allowed in this test");
        assert.deepEqual(errors, [], "No unhandled JavaScript errors");
    } finally {
        if (context) await context.request.post("/api/method/logout", { timeout: 5000 }).catch(() => {});
        await browser.close();
    }
})().catch(error => { console.error(error.message); process.exitCode = 1; });

