// Shared steps that follow what a user does in the Restaurant POS.
const { expect } = require("@playwright/test");

function credentials(role) {
    const user = process.env[`E2E_${role}_USER`];
    const password = process.env[`E2E_${role}_PASSWORD`];
    if (!user || !password) {
        throw new Error(`Define E2E_${role}_USER y E2E_${role}_PASSWORD para ejecutar esta prueba.`);
    }
    return { user, password };
}

async function login(page, role) {
    const { user, password } = credentials(role);
    const response = await page.request.post("/api/method/login", { form: { usr: user, pwd: password } });
    expect(response.ok(), `Inicio de sesión de ${user}`).toBeTruthy();
}

async function openPos(page) {
    await page.goto("/app/restaurant-pos");
    await expect(page.locator(".rpos-nav-tab", { hasText: "Caja" })).toBeVisible();
    await expect(page.locator(".rpos-prod-card").first()).toBeVisible();
    // A dialog at start (for example "Apertura de POS") means the seed data is incomplete.
    const dialog = page.locator(".rpos-modal-backdrop");
    if (await dialog.isVisible()) {
        const text = (await dialog.innerText()).replace(/\s+/g, " ").slice(0, 80);
        throw new Error(`El POS abrió una ventana antes de empezar ("${text}"). Si es la apertura de caja, abre el turno de este usuario.`);
    }
}

async function addProduct(page, itemName) {
    await page.locator(".rpos-prod-card", { hasText: itemName }).first().click();
    await expect(page.locator("[data-line-idx]", { hasText: itemName }).first()).toBeVisible();
}

module.exports = {
    addProduct,
    itemName: () => process.env.E2E_ITEM || "BALEADA",
    login,
    openPos,
};
