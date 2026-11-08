// Verify theme colors and scope using a dedicated, temporary development account.
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const { chromium } = require(process.env.LEAF_PLAYWRIGHT_MODULE || "playwright");
(async () => {
    const credentials = JSON.parse(fs.readFileSync(process.env.LEAF_UI_CREDENTIALS_FILE, "utf8"));
    const browser = await chromium.launch({ headless: true, ...(process.env.LEAF_UI_BROWSER ? { executablePath: process.env.LEAF_UI_BROWSER } : {}) });
    const output = process.env.LEAF_UI_OUTPUT || process.cwd();
    const result = {};
    try {
        const context = await browser.newContext({ baseURL: process.env.LEAF_UI_BASE_URL || "http://localhost:8000", viewport: { width: 1440, height: 1000 } });
        const login = await context.request.post("/api/method/login", { form: { usr: credentials.user, pwd: credentials.password } });
        assert(login.ok(), `Dedicated test account login failed: ${login.status()}`);
        const page = await context.newPage();
        const errors = [];
        page.on("pageerror", error => { errors.push(error.stack); console.error(error.stack); });
        const activePage = () => page.locator(".page-container:visible");
        const primary = () => activePage().locator(".page-actions .primary-action");
        const color = locator => locator.evaluate(e => {
            const s = getComputedStyle(e);
            return { background: s.backgroundColor, image: s.backgroundImage, color: s.color, outline: s.outlineColor, stroke: s.getPropertyValue("--icon-stroke").trim() };
        });
        const route = async (...parts) => {
            await page.evaluate(parts => frappe.set_route(...parts), parts);
            await page.waitForFunction(parts => JSON.stringify(frappe.get_route().slice(0, parts.length)) === JSON.stringify(parts), parts);
        };
        const readyItems = async () => {
            await primary().waitFor();
            await activePage().locator('.indicator-pill[data-filter="disabled,=,0"]').first().waitFor();
            await activePage().locator('.list-sidebar .list-sidebar-button').first().waitFor({ state: 'attached' });
        };
        const assertContext = async expected => assert.equal(await page.locator("body").evaluate(e => e.classList.contains("restaurant-theme-context")), expected);
        await page.goto("/app/item");
        await page.waitForFunction(() => !!window.frappe?.restaurant_theme);
        await readyItems();
        await page.locator('#navbar-search').waitFor();
        await assertContext(false);
        result.native_item = await color(primary());
        result.native_enabled = await color(activePage().locator('.indicator-pill[data-filter="disabled,=,0"]').first());
        result.native_filter = await color(activePage().locator('.filter-button'));
        result.native_sidebar = await color(activePage().locator('.list-sidebar-button').first());
        await route("Workspaces", "Restaurante");
        await page.locator('.lr-dashboard').waitFor();
        await page.locator('.restaurant-create-workspace:visible').waitFor();
        await assertContext(true);
        result.workspace_button = await color(page.locator('.restaurant-create-workspace:visible'));
        result.workspace_selected = await color(page.locator('[item-name="Restaurante"] > .desk-sidebar-item.selected'));
        result.workspace_edit = await color(activePage().locator('.page-actions .btn-secondary:visible').first());
        result.workspace_icon = await color(page.locator('.lr-card-icon').first());
        assert.equal(result.workspace_button.background, "rgb(0, 36, 86)");
        assert.equal(result.workspace_selected.background, "rgb(0, 36, 86)");
        assert.equal(result.workspace_edit.background, "rgb(47, 133, 0)");
        assert.equal(result.workspace_icon.color, "rgb(54, 153, 0)");
        await page.locator('[data-action="settings"]').click();
        await page.locator('.restaurant-theme-dialog:visible').waitFor();
        assert(await page.locator('.modal:visible').evaluate(e => e.classList.contains('restaurant-theme-dialog')), 'Workspace dialogs must inherit their Restaurant origin across the shadow root');
        await page.locator('.modal:visible .btn-modal-close').click();
        await page.screenshot({ path: path.join(output, 'restaurant-theme-workspace.png'), fullPage: true });
        await page.locator('[data-action="items"]').click();
        await readyItems();
        await assertContext(true);
        result.restaurant_item = await color(primary());
        result.restaurant_enabled = await color(activePage().locator('.indicator-pill[data-filter="disabled,=,0"]').first());
        result.restaurant_filter = await color(activePage().locator('.filter-button'));
        result.restaurant_filter_icon = await color(activePage().locator('.filter-button .icon').first());
        result.restaurant_sidebar = await color(activePage().locator('.list-sidebar-button').first());
        assert.equal(result.restaurant_item.background, "rgb(47, 133, 0)");
        assert.equal(result.restaurant_enabled.background, "rgb(239, 251, 233)");
        assert.equal(result.restaurant_enabled.color, "rgb(47, 133, 0)");
        assert.equal(result.restaurant_filter.outline, "rgb(164, 206, 135)");
        assert.equal(result.restaurant_sidebar.color, "rgb(47, 133, 0)");
        await page.reload();
        await readyItems();
        await assertContext(true);
        assert.deepEqual(await color(primary()), result.restaurant_item, 'A catalog reload must preserve its Restaurant origin');
        await page.screenshot({ path: path.join(output, 'restaurant-theme-items.png'), fullPage: true });
        await route('Workspaces', 'Restaurante');
        await page.locator('[data-action="items"]').click();
        await readyItems();
        await primary().click();
        await page.waitForFunction(() => frappe.get_route()[0] === 'Form' && window.cur_frm?.doc?.__islocal);
        await primary().waitFor();
        await page.waitForLoadState('networkidle');
        assert.equal((await color(primary())).background, 'rgb(47, 133, 0)');
        console.log('VERIFIED: Restaurant workspace, catalog, reload and new form');
        await route('Workspaces', 'Stock');
        await page.waitForFunction(() => !document.body.classList.contains('restaurant-theme-context'));
        await page.locator('[item-name="Stock"] > .desk-sidebar-item.selected').waitFor();
        result.stock_selected = await color(page.locator('[item-name="Stock"] > .desk-sidebar-item.selected'));
        assert.notEqual(result.stock_selected.background, 'rgb(0, 36, 86)');
        await route('List', 'Item');
        await readyItems();
        await assertContext(false);
        assert.deepEqual(await color(primary()), result.native_item, 'Native Item accessed from Stock must retain its original colors');
        assert.deepEqual(await color(activePage().locator('.indicator-pill[data-filter="disabled,=,0"]').first()), result.native_enabled);
        assert.deepEqual(await color(activePage().locator('.filter-button')), result.native_filter);
        assert.deepEqual(await color(activePage().locator('.list-sidebar-button').first()), result.native_sidebar);
        await page.screenshot({ path: path.join(output, 'restaurant-theme-native-item.png'), fullPage: true });
        console.log('VERIFIED: Stock and native Item colors restored');
        // Native informational dialogs from a new Item may finish loading after navigation.
        for (let index = 0; index < 5 && await page.locator('.modal:visible').count(); index++) {
            const dialog = page.locator('.modal:visible').last();
            await dialog.locator('.btn-modal-close').click();
            await dialog.waitFor({ state: 'hidden' });
        }
        await route('Workspaces', 'Restaurante');
        await page.locator('[data-action="locations"]').click();
        await page.locator('.ra-app').waitFor();
        await assertContext(true);
        assert.equal(await page.locator('.ra-app').evaluate(e => getComputedStyle(e).getPropertyValue('--ra-blue').trim()), '#2f8500');
        await route('Workspaces', 'Restaurante');
        await page.locator('[data-action="table-map"]').click();
        await page.locator('.rtm-app').waitFor();
        await assertContext(true);
        assert.equal(await page.locator('.rtm-app').evaluate(e => getComputedStyle(e).getPropertyValue('--rtm-sky').trim()), '#2f8500');
        // Exercise every implemented shared catalog destination from the Workspace.
        result.catalog_destinations = [];
        for (const [action, expectedRoute] of [
            ['tables', ['List', 'Restaurant Table']], ['waiters', ['List', 'Employee']],
            ['groups', ['Tree', 'Item Group']], ['prices', ['List', 'Item Price']],
            ['customers', ['List', 'Customer']],
        ]) {
            console.log(`CHECKING: ${action}`);
            await route('Workspaces', 'Restaurante');
            await page.locator(`[data-action="${action}"]`).click();
            await page.waitForFunction(expected => JSON.stringify(frappe.get_route().slice(0, expected.length)) === JSON.stringify(expected), expectedRoute).catch(async error => {
                console.error(JSON.stringify(await page.evaluate(() => ({ route: frappe.get_route(), modal: [...document.querySelectorAll('.modal.show .modal-title')].map(node => node.innerText) }))));
                throw error;
            });
            await assertContext(true);
            await page.waitForLoadState('networkidle');
            if (await primary().isVisible()) assert.equal((await color(primary())).background, 'rgb(47, 133, 0)');
            const filter = activePage().locator('.filter-button');
            if (await filter.count()) assert.equal((await color(filter)).color, 'rgb(47, 133, 0)');
            result.catalog_destinations.push(action);
        }
        for (const [action, expectedType] of [['branches', 'Branch'], ['price-lists', 'Price List'], ['uoms', 'UOM']]) {
            await route('Workspaces', 'Restaurante');
            await page.locator('[data-action="settings"]').click();
            const dialog = page.locator('.modal:visible').last();
            const index = ['branches', 'price-lists', 'uoms'].findIndex(key => key === action);
            await dialog.locator('.modal-body button').nth(index).click();
            await page.waitForFunction(type => frappe.get_route()[0] === 'List' && frappe.get_route()[1] === type, expectedType);
            await primary().waitFor(); await assertContext(true);
            assert.equal((await color(primary())).background, 'rgb(47, 133, 0)');
            result.catalog_destinations.push(action);
        }
        for (const [index, report] of ['Sales Analytics', 'Sales Register', 'Item-wise Sales Register'].entries()) {
            await route('Workspaces', 'Restaurante');
            await page.locator('[data-action="reports"]').click();
            const dialog = page.locator('.modal:visible').last();
            await dialog.locator('.modal-body button').nth(index).click();
            await page.waitForFunction(name => frappe.get_route()[0] === 'query-report' && frappe.get_route()[1] === name, report);
            await assertContext(true);
            result.catalog_destinations.push(report);
        }
        await route('Workspaces', 'Restaurante');
        await page.locator('[data-action="items"]').click();
        await readyItems();
        await assertContext(true);
        // Select an actual native global-search result, including its normal navigation event.
        await page.locator('#navbar-search').fill('Producto');
        await page.waitForFunction(() => {
            const input = document.querySelector('#navbar-search');
            return [...input.awesomplete.ul.children].some(node => $(node).data('item.autocomplete')?.route?.[1] === 'Item');
        });
        await page.evaluate(() => {
            const input = document.querySelector('#navbar-search');
            const option = [...input.awesomplete.ul.children].find(node => $(node).data('item.autocomplete')?.route?.[1] === 'Item');
            option.setAttribute('data-restaurant-theme-search-test', 'true');
        });
        await page.locator('[data-restaurant-theme-search-test]').click();
        await assertContext(false);
        await route('List', 'Item');
        assert.deepEqual(await color(primary()), result.native_item);
        await route('Workspaces', 'Restaurante');
        await page.locator('[data-action="items"]').click();
        await readyItems();
        await route('List', 'Sales Invoice');
        await primary().waitFor();
        await assertContext(false);
        assert.notEqual((await color(primary())).background, 'rgb(47, 133, 0)', 'Unrelated transactions must keep their original palette');
        // The custom stylesheet must not alter native layout or unrelated status colors.
        const isolation = await page.evaluate(async () => {
            await frappe.set_route('List', 'Item');
            const container = document.querySelector('[data-page-route^="List/Item/"]');
            const button = container.querySelector('.primary-action');
            const probe = document.createElement('span'); probe.className = 'indicator-pill red'; container.appendChild(probe);
            const read = () => ({ rect: JSON.stringify(button.getBoundingClientRect().toJSON()), red: getComputedStyle(probe).color, background: getComputedStyle(probe).backgroundColor });
            const before = read(); document.body.classList.add('restaurant-theme-context'); const after = read();
            document.body.classList.remove('restaurant-theme-context'); probe.remove();
            return { before, after };
        });
        assert.deepEqual(isolation.after, isolation.before, 'Only colors requested for Restaurant may change; geometry and red statuses must remain intact');
        assert.deepEqual(errors, [], 'No JavaScript runtime errors are allowed');
        result.verified = ['workspace_icons', 'workspace_navy', 'primary_buttons', 'enabled_item', 'filter', 'sidebar_links', 'reload', 'new_item_form', 'stock_isolation', 'global_search_isolation', 'other_transactions', 'area_and_map', 'dialog_origin', 'layout_and_red_status'];
        result.javascript_errors = errors;
        fs.writeFileSync(path.join(output, 'restaurant-theme-result.json'), JSON.stringify(result, null, 2));
        console.log(JSON.stringify(result));
    } finally { await browser.close(); }
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
