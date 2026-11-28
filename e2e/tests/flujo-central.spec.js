// Central flow: a cashier charges an order and gets its SAR invoice from the browser.
const { test, expect } = require("@playwright/test");
const { addProduct, itemName, login, openPos } = require("./helpers");

test("Dado un cajero con turno abierto, cuando cobra una cuenta en efectivo, entonces ve la factura SAR emitida", async ({ page }) => {
    await login(page, "CASHIER");
    await openPos(page);

    await addProduct(page, itemName());
    await page.locator(".rpos-bottom-btn.is-pay", { hasText: "Pago" }).click();

    await page.locator('[data-action="pay-screen-mop"][data-mop="Efectivo"]').click();
    await page.locator('[data-action="pay-screen-validate"]').click();

    await expect(page.getByText("Importe pagado")).toBeVisible();
    const meta = page.locator(".rpos-pay-success-meta");
    await expect(meta).toContainText("Factura Fiscal SAR:");
    const invoiceName = (await meta.locator("strong").innerText()).trim();

    // The invoice really exists and is submitted in ERPNext.
    const response = await page.request.get(`/api/resource/Sales Invoice/${encodeURIComponent(invoiceName)}`);
    expect(response.ok()).toBeTruthy();
    const invoice = (await response.json()).data;
    expect(invoice.docstatus).toBe(1);
    expect(invoice.items.some(row => row.item_name === itemName())).toBeTruthy();
});
