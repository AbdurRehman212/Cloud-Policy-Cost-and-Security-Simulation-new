// Runs against already-running servers (see README "Restart"): frontend :3000, backend :5000.
// Uses the installed Google Chrome, so no browser download is needed.
const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './tests',
  timeout: 90_000,
  workers: 1,
  reporter: [['list']],
  use: { baseURL: process.env.E2E_BASE_URL || 'http://localhost:3000', channel: 'chrome', headless: true, acceptDownloads: true },
});
