const { defineConfig } = require('@playwright/test');
module.exports = defineConfig({
  testDir: './tests/e2e',
  timeout: 90000,
  expect: { timeout: 45000 },
  workers: 1,
  fullyParallel: false,
  reporter: [['list'], ['json', { outputFile: 'runtime/browser-results.json' }]],
  outputDir: 'runtime/browser-artifacts',
  use: {
    baseURL: 'http://127.0.0.1:18767',
    channel: process.platform === 'win32' ? 'msedge' : undefined,
    viewport: { width: 1512, height: 982 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure'
  },
  webServer: {
    command: process.platform === 'win32' ? '.venv\\Scripts\\python.exe tests/e2e/serve.py' : '.venv/bin/python tests/e2e/serve.py',
    url: 'http://127.0.0.1:18767/health',
    reuseExistingServer: false,
    timeout: 20000
  }
});
