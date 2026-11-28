// Critical permission: a waiter can take an order but cannot charge it.
const { test, expect } = require("@playwright/test");
const { addProduct, itemName, login, openPos } = require("./helpers");

test("Dado un mesero, cuando agrega un producto a una cuenta, entonces no ve la opción de cobrar", async ({ page }) => {
    await login(page, "WAITER");
    await openPos(page);

    await addProduct(page, itemName());

    await expect(page.locator(".rpos-bottom-btn.is-pay")).toHaveCount(0);
    await expect(page.getByText("Importe pagado")).toHaveCount(0);
});
