// @ts-check
const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './tests',
  timeout: 30_000,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.PANEL_BASE_URL || 'http://localhost:4300',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
});
