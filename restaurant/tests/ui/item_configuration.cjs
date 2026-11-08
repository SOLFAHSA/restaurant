// Run against a development site with a dedicated temporary test account.
// Never read existing session cookies or put credentials in source control.
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const { chromium } = require(process.env.LEAF_PLAYWRIGHT_MODULE || "playwright");

(async () => {
    assert(process.env.LEAF_UI_CREDENTIALS_FILE, "A dedicated test credential file is required");
    assert(process.env.LEAF_UI_ITEM, "An existing test Item is required");
    const credentials = JSON.parse(fs.readFileSync(process.env.LEAF_UI_CREDENTIALS_FILE, "utf8"));
    const output = process.env.LEAF_UI_OUTPUT || process.cwd();
    const browser = await chromium.launch({
        headless: true,
        ...(process.env.LEAF_UI_BROWSER ? { executablePath: process.env.LEAF_UI_BROWSER } : {}),
    });
    try {
        const context = await browser.newContext({
            baseURL: process.env.LEAF_UI_BASE_URL || "http://localhost:8000",
            viewport: { width: 1366, height: 900 },
        });
        const login = await context.request.post("/api/method/login", {
            form: { usr: credentials.user, pwd: credentials.password },
        });
        assert(login.ok(), `Test account login failed: ${login.status()}`);
        const page = await context.newPage();
        const errors = [];
        page.on("pageerror", error => errors.push(error.message));
        await page.goto(`/app/item/${encodeURIComponent(process.env.LEAF_UI_ITEM)}`);
        await page.waitForFunction(item => window.cur_frm?.doc?.name === item, process.env.LEAF_UI_ITEM);
        await page.waitForFunction(() => Boolean(window.cur_frm?.restaurant_editor?.context));
        await page.getByRole("tab", { name: "Restaurante", exact: true }).click();
        const components = page.getByRole("button", { name: "Agregar componentes", exact: true });
        const options = page.getByRole("button", { name: "Agregar grupo de opciones", exact: true });
        await components.waitFor({ state: "visible" });
        await options.waitFor({ state: "visible" });
        assert(await components.isEnabled(), "The recipe action must be enabled");
        assert(await options.isEnabled(), "The options action must be enabled");
        await page.screenshot({ path: path.join(output, "restaurant-editor-verified.png"), fullPage: true });

        await components.click();
        let dialog = page.locator(".modal:visible").last();
        await dialog.locator(".grid-add-row").click();
        let row = dialog.locator('.grid-body .grid-row[data-idx="1"]').first();
        await row.locator('[data-fieldname="item_code"]').first().click();
        const ingredient = row.locator('[data-fieldname="item_code"] input').first();
        await ingredient.waitFor({ state: "visible" });
        const searchPromise = page.waitForResponse(response =>
            response.url().includes("frappe.desk.search.search_link") &&
            (response.request().postData() || response.url()).includes("Papa")
        );
        await ingredient.fill("Papa");
        const search = await searchPromise;
        assert(search.ok(), `Ingredient search failed: ${search.status()}`);
        const searchData = await search.json();
        assert(!searchData.exc && !searchData.exception, "Ingredient lookup returned an application error");
        await ingredient.fill("");
        await row.locator('[data-fieldname="qty"]').first().click();
        await row.locator('[data-fieldname="qty"] input').first().waitFor({ state: "visible" });
        await row.locator('[data-fieldname="uom"]').first().click();
        await row.locator('[data-fieldname="uom"] input').first().waitFor({ state: "visible" });
        await dialog.screenshot({ path: path.join(output, "restaurant-components-verified.png") });
        await dialog.locator(".modal-header .btn-modal-close").click();
        await dialog.waitFor({ state: "hidden" });

        await options.click();
        dialog = page.locator(".modal:visible").last();
        await dialog.locator('input[data-fieldname="group_name"]').waitFor({ state: "visible" });
        await dialog.locator(".grid-add-row").click();
        row = dialog.locator('.grid-body .grid-row[data-idx="1"]').first();
        await row.locator('[data-fieldname="effect"]').first().click();
        const effect = row.locator('[data-fieldname="effect"] select').first();
        await effect.waitFor({ state: "visible" });
        assert.deepEqual(await effect.locator("option").allTextContents(), [
            "Solo indicación", "Sustituir componente", "Agregar componente", "Incluir en combo",
        ]);
        await row.locator('[data-fieldname="additional_amount"]').first().click();
        await row.locator('[data-fieldname="additional_amount"] input').first().waitFor({ state: "visible" });
        await row.locator(".btn-open-row").click();
        for (const field of ["item_code", "replaces_item", "qty", "uom"]) {
            await dialog.locator(`[data-fieldname="${field}"] input`).last().waitFor({ state: "visible" });
        }
        await dialog.locator('[data-fieldname="is_default"] input[type="checkbox"]:visible:not([disabled])').first().waitFor({ state: "visible" });
        await dialog.screenshot({ path: path.join(output, "restaurant-options-verified.png") });
        await dialog.locator(".modal-header .btn-modal-close").click();
        await dialog.waitFor({ state: "hidden" });
        assert.equal(await page.evaluate(() => cur_frm.is_dirty()), false, "The test must not edit the Item");
        assert.deepEqual(errors, [], "No JavaScript errors are allowed");
        const result = {
            editor_visible: true, ingredient_search_status: search.status(),
            recipe_quantity_and_uom_visible: true, option_effects_and_surcharge_visible: true,
            option_ingredient_details_visible: true, item_not_modified: true, javascript_errors: 0,
        };
        fs.writeFileSync(path.join(output, "restaurant-editor-ui-result.json"), JSON.stringify(result, null, 2));
        console.log(JSON.stringify(result));
    } finally {
        await browser.close();
    }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
