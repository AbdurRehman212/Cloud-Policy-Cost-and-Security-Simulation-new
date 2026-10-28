const { test, expect } = require('@playwright/test');

// One serial journey: each step builds on the data created by the previous one.
test.describe.configure({ mode: 'serial' });

const stamp = Date.now().toString(36);
const user = { first: 'E2E', last: 'Runner', email: `e2e_${stamp}@example.com`, password: 'Str0ng!Pass123' };
const vmName = `web-e2e-${stamp}`;
let page;
const pageErrors = [];

test.beforeAll(async ({ browser }) => {
  page = await (await browser.newContext({ acceptDownloads: true })).newPage();
  page.on('pageerror', (error) => pageErrors.push(error.message)); // uncaught exceptions only
});
test.afterAll(async () => page.context().close());

const goto = async (path) => {
  await page.goto(path);
  await page.waitForLoadState('networkidle');
};

test('M1 rejects bad credentials, registers and logs in', async () => {
  await goto('/login');
  await page.getByPlaceholder('you@example.com').fill('nobody@example.com');
  await page.getByPlaceholder('••••••••').fill('Wrong!Pass123');
  await page.getByRole('button', { name: 'Sign In' }).click();
  await expect(page).toHaveURL(/login/);

  await goto('/register');
  const boxes = page.getByRole('textbox');
  await boxes.nth(0).fill(user.first);
  await boxes.nth(1).fill(user.last);
  await page.getByPlaceholder('you@example.com').fill(user.email);
  await page.getByPlaceholder('Min 8 characters').fill(user.password);
  await boxes.nth(4).fill(user.password);
  await page.getByRole('button', { name: 'Create Account' }).click();
  await expect(page.getByRole('button', { name: 'Sign In' })).toBeVisible();

  await page.getByPlaceholder('you@example.com').fill(user.email);
  await page.getByPlaceholder('••••••••').fill(user.password);
  await page.getByRole('button', { name: 'Sign In' }).click();
  await expect(page.getByRole('heading', { name: 'Resource Operations Dashboard' })).toBeVisible();
  // New accounts are offered the guided tour; the tour itself is covered in tour.spec.js
  await page.getByTestId('tour-skip-welcome').click();
});

test('M2 default organization is created with the owner role', async () => {
  await expect(page.getByRole('button', { name: /Cloud Workspace.*owner/i })).toBeVisible();
});

test('dashboard realtime stream connects (shows Live, not Reconnecting)', async () => {
  await expect(page.getByText('Live', { exact: true })).toBeVisible({ timeout: 20_000 });
});

test('M4/M5 creates a VM and shows its live metrics', async () => {
  await goto('/resources');
  await page.getByRole('button', { name: 'Create VM' }).first().click();
  await page.getByPlaceholder('e.g., web-server-01').fill(vmName);
  await page.getByRole('button', { name: 'Create VM' }).last().click();
  // The detail modal (with metrics) opens automatically after creation.
  await expect(page.getByRole('heading', { name: vmName, level: 3 })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Metrics' })).toBeVisible();
  await expect(page.getByText('CPU Usage').first()).toBeVisible();
});

test('M7 policy is created and evaluated with violations', async () => {
  await goto('/governance');
  await page.getByRole('button', { name: 'Create Policy' }).first().click();
  await page.getByPlaceholder('Encrypt production databases').fill('Prod naming');
  await page.getByPlaceholder(/Examples: all databases/).fill('VM names must start with prod-');
  await page.getByRole('button', { name: 'Create Policy' }).last().click();
  await expect(page.getByRole('heading', { name: 'Prod naming' })).toBeVisible();
  await page.getByRole('button', { name: 'Run Compliance Check' }).click();
  await expect(page.getByRole('heading', { name: /Open Violations \([1-9]/ })).toBeVisible();
});

test('M8 cost page lists per-resource costs and creates a budget', async () => {
  const table = page.getByTestId('resource-cost-table');
  // Cost rows are written by simulator ticks shortly after the VM starts running.
  await expect(async () => {
    await goto('/cost');
    await expect(table.getByRole('cell', { name: vmName })).toBeVisible({ timeout: 1500 });
  }).toPass({ timeout: 60_000 });
  await page.getByRole('button', { name: 'Create Budget' }).first().click();
  await page.locator('input[type=number]').first().fill('250');
  await page.getByRole('button', { name: 'Save Budget' }).click();
  await expect(page.getByText(/of \$250\.00/)).toBeVisible();
});

test('M9 downloads a PDF and a CSV report', async () => {
  await goto('/reports');
  const [pdf] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Download PDF' }).first().click(),
  ]);
  expect(pdf.suggestedFilename()).toMatch(/\.pdf$/i);
  const [csv] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Cost Records (CSV)' }).click(),
  ]);
  expect(csv.suggestedFilename()).toMatch(/\.csv$/i);
});

test('M6 simulated attack is recorded and labelled as simulated, not as a model score', async () => {
  await goto('/security');
  await page.getByRole('button', { name: 'Simulate Attack' }).first().click();
  await expect(page.getByText(/not a prediction\s+by the machine-learning detector/)).toBeVisible();
  await page.getByRole('button', { name: 'Simulate Attack' }).last().click();
  await expect(page.getByText('Simulated (no model score)').first()).toBeVisible();
});

test('no uncaught browser exceptions during the whole journey', async () => {
  expect(pageErrors).toEqual([]);
});
