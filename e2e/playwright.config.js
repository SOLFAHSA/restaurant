// End-to-end tests run against a development or test site with seed data, never production.
const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
    testDir: "./tests",
    timeout: 90_000,
    expect: { timeout: 20_000 },
    fullyParallel: false,
    workers: 1,
    retries: 0,
    reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
    use: {
        baseURL: process.env.E2E_BASE_URL || "http://localhost:8000",
        viewport: { width: 1440, height: 960 },
        screenshot: "on",
        trace: "retain-on-failure",
        locale: "es-HN",
    },
});
