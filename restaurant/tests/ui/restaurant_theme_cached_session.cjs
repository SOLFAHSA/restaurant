// Regression: a Desk document and sprite cached before theme assets were registered.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.LEAF_PLAYWRIGHT_MODULE || 'playwright');
(async () => {
    const credentials = JSON.parse(fs.readFileSync(process.env.LEAF_UI_CREDENTIALS_FILE, 'utf8'));
    const browser = await chromium.launch({ headless: true, ...(process.env.LEAF_UI_BROWSER ? { executablePath: process.env.LEAF_UI_BROWSER } : {}) });
    try {
        const context = await browser.newContext({ baseURL: process.env.LEAF_UI_BASE_URL || 'http://localhost:8000', viewport: { width: 1440, height: 1000 } });
        const login = await context.request.post('/api/method/login', { form: { usr: credentials.user, pwd: credentials.password } });
        assert(login.ok());
        const errors = [];
        const iconSource = fs.readFileSync(process.env.LEAF_UI_ICON_SOURCE || path.resolve(__dirname, '../../public/js/restaurant_icons.js'), 'utf8');
        assert(!iconSource.includes('restaurant_theme'), 'The sprite must remain independent of the theme');
        await context.route('**/assets/restaurant/js/restaurant_icons.js', route => route.fulfill({ contentType: 'application/javascript', body: iconSource }));
        // Model an already loaded Desk document whose theme assets were absent.
        let recoverAssets = false;
        await context.route('**/assets/restaurant/css/restaurant_theme.css?*', route => recoverAssets
            ? route.continue() : route.fulfill({ contentType: 'text/css', body: '' }));
        await context.route('**/assets/restaurant/js/restaurant_theme.js?*', async route => {
            if (!recoverAssets) return route.fulfill({ contentType: 'application/javascript', body: '' });
            await new Promise(resolve => setTimeout(resolve, 1200));
            await route.continue();
        });
        const page = await context.newPage();
        page.on('pageerror', error => errors.push(error.stack));
        await page.goto('/app/item');
        const primary = () => page.locator('.page-container:visible .primary-action');
        await primary().waitFor();
        assert.equal(await page.evaluate(() => Boolean(frappe.restaurant_theme)), false);
        const nativeColor = await primary().evaluate(e => getComputedStyle(e).backgroundColor);
        await page.evaluate(() => document.querySelectorAll('link[href*="restaurant_theme.css"]').forEach(node => node.remove()));
        recoverAssets = true;
        await page.evaluate(() => { frappe.set_route('Workspaces', 'Restaurante'); });
        await page.locator('.lr-dashboard').waitFor();
        const pendingAtClick = await page.evaluate(() => !frappe.restaurant_theme);
        assert(pendingAtClick, 'The test must exercise navigation while theme loading is pending');
        await page.locator('[data-action="items"]').click();
        await page.waitForFunction(() => frappe.get_route()[0] === 'List' && frappe.get_route()[1] === 'Item');
        await primary().waitFor();
        assert.equal(await primary().evaluate(e => getComputedStyle(e).backgroundColor), 'rgb(47, 133, 0)');
        await page.evaluate(() => frappe.set_route('Workspaces', 'Restaurante'));
        await page.locator('.restaurant-create-workspace:visible').waitFor();
        assert.equal(await page.locator('.restaurant-create-workspace:visible').evaluate(e => getComputedStyle(e).backgroundColor), 'rgb(0, 36, 86)');
        assert.equal(await page.locator('[item-name="Restaurante"] > .selected').evaluate(e => getComputedStyle(e).backgroundColor), 'rgb(0, 36, 86)');
        assert.equal(await page.locator('.page-container:visible .page-actions .btn-secondary').first().evaluate(e => getComputedStyle(e).backgroundColor), 'rgb(47, 133, 0)');
        assert.equal(await page.locator('link[href*="restaurant_theme.css"]').count(), 1);
        await page.screenshot({ path: path.join(process.env.LEAF_UI_OUTPUT || process.cwd(), 'restaurant-theme-cached-session.png'), fullPage: true });
        await page.evaluate(() => frappe.set_route('Workspaces', 'Stock'));
        await page.waitForFunction(() => !document.body.classList.contains('restaurant-theme-context'));
        await page.evaluate(() => frappe.set_route('List', 'Item'));
        await primary().waitFor();
        assert.equal(await primary().evaluate(e => getComputedStyle(e).backgroundColor), nativeColor);
        assert.deepEqual(errors, []);
        const failureContext = await browser.newContext({ baseURL: process.env.LEAF_UI_BASE_URL || 'http://localhost:8000' });
        const failureLogin = await failureContext.request.post('/api/method/login', { form: { usr: credentials.user, pwd: credentials.password } });
        assert(failureLogin.ok());
        let allowStyle = false;
        let styleAttempts = 0;
        await failureContext.route('**/assets/restaurant/css/restaurant_theme.css?*', route => {
            styleAttempts++;
            return allowStyle ? route.continue() : route.abort();
        });
        const failurePage = await failureContext.newPage();
        failurePage.on('pageerror', error => errors.push(error.stack));
        await failurePage.goto('/app/restaurante');
        await failurePage.locator('[data-action="items"]').click();
        await failurePage.waitForFunction(() => frappe.get_route()[0] === 'List' && frappe.get_route()[1] === 'Item');
        const failurePrimary = () => failurePage.locator('.page-container:visible .primary-action');
        await failurePrimary().waitFor();
        assert.equal(await failurePrimary().evaluate(e => getComputedStyle(e).backgroundColor), nativeColor, 'A failed stylesheet must not block opening the native catalog');
        allowStyle = true;
        await failurePage.evaluate(() => frappe.set_route('Workspaces', 'Restaurante'));
        await failurePage.locator('[data-action="items"]').click();
        await failurePage.waitForFunction(() => frappe.get_route()[0] === 'List' && frappe.get_route()[1] === 'Item');
        await failurePrimary().waitFor();
        assert.equal(await failurePrimary().evaluate(e => getComputedStyle(e).backgroundColor), 'rgb(47, 133, 0)', 'A subsequent attempt must fetch a fresh stylesheet');
        assert(styleAttempts >= 3);
        assert.equal(await failurePage.locator('link[href*="restaurant_theme.css"]').count(), 1);
        assert.deepEqual(errors, []);
        console.log(JSON.stringify({ cached_desk_recovered: true, delayed_assets: true, immediate_click: true, stock_unchanged: true, failed_css_keeps_native_navigation: true, css_retry_verified: true, javascript_errors: errors }));
    } finally { await browser.close(); }
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
