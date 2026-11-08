// Run only with an explicitly authorized, dedicated temporary test account.
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const { chromium } = require(process.env.LEAF_PLAYWRIGHT_MODULE || "playwright");

(async () => {
    assert(process.env.LEAF_UI_CREDENTIALS_FILE, "A dedicated credential file is required");
    const credentials = JSON.parse(fs.readFileSync(process.env.LEAF_UI_CREDENTIALS_FILE, "utf8"));
    const output = process.env.LEAF_UI_OUTPUT || process.cwd();
    fs.mkdirSync(output, { recursive: true });
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
        assert(login.ok(), "Dedicated test login failed");
        const page = await context.newPage();
        const errors = [];
        page.on("pageerror", error => errors.push(error.message));
        const api = args => page.evaluate(async args => {
            const response = await frappe.call({ method: "restaurant.commands.get_commands", args });
            return response.message.items;
        }, args);
        const modal = () => page.locator(".modal:visible").last();
        const field = (dialog, name) => dialog.locator(`[data-fieldname="${name}"] input`).first();
        await page.goto("/app/restaurante");
        await page.locator('[data-action="tickets"]').waitFor({ state: "visible" });
        await page.locator('[data-action="tickets"]').click();
        await page.waitForURL("**/app/restaurant-commands");
        await page.getByRole("button", { name: "Nueva comanda", exact: true }).waitFor();
        assert.deepEqual(await api({ search: credentials.prefix }), []);
        assert(await page.locator("body").evaluate(node => node.classList.contains("restaurant-theme-context")));

        // Cancel creates no document.
        await page.getByRole("button", { name: "Nueva comanda", exact: true }).click();
        await field(modal(), "command_name").fill(credentials.prefix + " cancelada");
        await modal().getByRole("button", { name: "Cancelar", exact: true }).click();
        assert.deepEqual(await api({ search: credentials.prefix }), []);

        const create = async (label, selectedGroups) => {
            await page.getByRole("button", { name: "Nueva comanda", exact: true }).click();
            const dialog = modal();
            await field(dialog, "command_name").fill(label);
            await field(dialog, "branch").fill(credentials.branch);
            await field(dialog, "branch").press("Tab");
            for (const name of selectedGroups) {
                await dialog.locator('.rc-group-list input[type="checkbox"]').evaluateAll((nodes, value) => {
                    const input = nodes.find(node => node.value === value);
                    if (!input) throw new Error("Missing native group " + value);
                    input.click();
                }, name);
            }
            await dialog.getByRole("button", { name: "Guardar", exact: true }).click();
            await dialog.waitFor({ state: "hidden" });
            await page.waitForFunction(label => document.querySelector(".rc-table tbody")?.textContent.includes(label), label);
        };
        await create(credentials.prefix + " Cocina", credentials.groups);
        await create(credentials.prefix + " Copia", [credentials.groups[0]]);
        let rows = await api({ search: credentials.prefix });
        assert.equal(rows.length, 2, "Both destinations must be saved");
        assert(rows.every(row => row.groups.includes(credentials.groups[0])), "The same group is allowed at both destinations");

        const kitchen = page.locator(".rc-table tbody tr").filter({ hasText: credentials.prefix + " Cocina" });
        await kitchen.getByRole("button", { name: "Editar", exact: true }).click();
        let dialog = modal();
        assert.equal(await field(dialog, "branch").inputValue(), credentials.branch);
        assert.equal(await dialog.locator('.rc-group-list input[type="checkbox"]:checked').count(), 2);
        await field(dialog, "command_name").fill(credentials.prefix + " editada");
        await dialog.getByRole("button", { name: "Cancelar", exact: true }).click();
        rows = await api({ search: credentials.prefix });
        assert(rows.some(row => row.command_name === credentials.prefix + " Cocina"), "Cancel must preserve the saved name");

        await kitchen.getByRole("button", { name: "Editar", exact: true }).click();
        dialog = modal();
        await field(dialog, "enabled").uncheck();
        await dialog.getByRole("button", { name: "Guardar", exact: true }).click();
        await dialog.waitFor({ state: "hidden" });
        await page.waitForFunction(label => [...document.querySelectorAll(".rc-table tbody tr")].some(row => row.textContent.includes(label) && row.textContent.includes("Inactiva")), credentials.prefix + " Cocina");
        await page.screenshot({ path: path.join(output, "comandas-escritorio.png"), fullPage: true });

        await page.getByRole("button", { name: "Nueva comanda", exact: true }).click();
        dialog = modal();
        await field(dialog, "command_name").fill(credentials.prefix + " sin grupos");
        await field(dialog, "branch").fill(credentials.branch);
        await field(dialog, "branch").press("Tab");
        await dialog.getByRole("button", { name: "Guardar", exact: true }).click();
        await page.getByText("Selecciona al menos un grupo para la comanda.", { exact: true }).waitFor();
        await page.keyboard.press("Escape");
        // Close the editor after the validation message.
        if (await page.locator(".rc-picker:visible").count()) {
            await modal().getByRole("button", { name: "Cancelar", exact: true }).click();
        }
        assert.equal((await api({ search: credentials.prefix })).length, 2);

        await page.setViewportSize({ width: 390, height: 844 });
        await page.getByRole("button", { name: "Nueva comanda", exact: true }).click();
        dialog = modal();
        await dialog.getByPlaceholder("Buscar grupo", { exact: true }).fill(credentials.groups[0]);
        assert.equal(await dialog.locator('.rc-group-list input[type="checkbox"]').count(), 1);
        await dialog.screenshot({ path: path.join(output, "comandas-modal-movil.png") });
        await dialog.getByRole("button", { name: "Cancelar", exact: true }).click();
        assert.equal(errors.length, 0, errors.join("\n"));
        console.log("VERIFIED: dashboard route, create, shared groups, edit, cancel, required groups, desktop and mobile; no page errors.");
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });

