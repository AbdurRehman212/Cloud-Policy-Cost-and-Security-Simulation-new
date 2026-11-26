// Cross-module scenario for Modules 10–12 (Remediation Agent, Audit Trail, User Settings), wired
// through Modules 1–9: register → preferences → resources → attack → policy → cost →
// remediation (approve + execute) → verified state → audit history → reports.
// Each run uses a fresh account and organization, so existing users and data are untouched.
const { test, expect } = require('@playwright/test');

test.describe.configure({ mode: 'serial' });

const API = process.env.E2E_API_URL || 'http://localhost:5000/api';
const stamp = Date.now().toString(36);
const user = { email: `m1012_${stamp}@example.com`, password: 'Str0ng!Pass123' };
let page;
let token;
let orgId;
let vm;
const pageErrors = [];
const shot = async (name) => {
  if (process.env.E2E_SHOTS) await page.screenshot({ path: `${process.env.E2E_SHOTS}/flow_${name}.png`, fullPage: true });
};

const api = async (method, path, data) => {
  const res = await page.request.fetch(`${API}${path}`, {
    method, data, headers: { Authorization: `Bearer ${token}` },
  });
  return { status: res.status(), body: res.headers()['content-type']?.includes('json') ? await res.json() : null };
};

test.beforeAll(async ({ browser }) => {
  page = await (await browser.newContext({ acceptDownloads: true })).newPage();
  page.on('pageerror', (error) => pageErrors.push(error.message));
});
test.afterAll(async () => page.context().close());

test('M1/M2 register, sign in and get an owned organization', async () => {
  const reg = await page.request.post(`${API}/auth/register`, {
    data: { email: user.email, password: user.password, first_name: 'Rem', last_name: 'Ediation' },
  });
  expect(reg.status()).toBe(201);
  await page.goto('/login');
  await page.getByPlaceholder('you@example.com').fill(user.email);
  await page.getByPlaceholder('••••••••').fill(user.password);
  await page.getByRole('button', { name: 'Sign In' }).click();
  await expect(page.getByRole('heading', { name: 'Resource Operations Dashboard' })).toBeVisible();
  await page.getByTestId('tour-skip-welcome').click();
  token = await page.evaluate(() => localStorage.getItem('token'));
  const orgs = await api('GET', '/org/');
  orgId = (orgs.body.data.organizations || orgs.body.data)[0].id;
  expect(orgId).toBeTruthy();
});

test('M12 preferences are validated, saved and applied after reload', async () => {
  await page.goto('/settings');
  await expect(page.getByRole('heading', { name: 'Settings', exact: true })).toBeVisible();
  await shot('m12_settings');
  await page.getByRole('button', { name: 'Alerts', exact: true }).click();
  await page.getByLabel('Cost alert threshold (% of budget)').fill('abc');
  await page.getByRole('button', { name: 'Save changes' }).click();
  await expect(page.getByRole('alert')).toHaveText('Cost threshold must be numeric'); // UT-70

  await page.getByRole('button', { name: 'Appearance', exact: true }).click();
  await page.getByLabel('Theme').selectOption('dark');
  await page.getByLabel('Date format').selectOption('DD/MM/YYYY');
  await page.getByRole('button', { name: 'Save changes' }).click();
  await expect(page.getByText('Settings saved').first()).toBeVisible();

  await page.getByRole('button', { name: 'Dashboard', exact: true }).click();
  await page.getByLabel('Default resource view').selectOption('list');
  await page.getByLabel('Default organization').selectOption(String(orgId));
  await page.getByRole('button', { name: 'Save changes' }).click();
  await expect(page.getByText('Settings saved').first()).toBeVisible();

  await page.reload();
  await expect(page.locator('html')).toHaveClass(/dark/); // theme applied from the server copy
  const saved = await api('GET', '/settings');
  expect(saved.body.data.appearance).toMatchObject({ theme: 'dark', date_format: 'DD/MM/YYYY' });
  expect(saved.body.data.dashboard).toMatchObject({ default_view: 'list', default_organization_id: orgId });
});

test('M4/M5 resources: a VM is created and the saved list layout is used', async () => {
  const created = await api('POST', '/resources/vm', { organization_id: orgId, name: `web-${stamp}`, instance_type: 't2.micro' });
  expect(created.status).toBeLessThan(300);
  await expect.poll(async () => {
    const list = await api('GET', `/resources/vm?organization_id=${orgId}`);
    vm = (list.body.data || list.body.vms || []).find((v) => v.name === `web-${stamp}`);
    return vm?.status;
  }, { timeout: 20000 }).toBe('running');
  await page.goto('/resources');
  await expect(page.getByRole('button', { name: 'List', pressed: true })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: '$/hour' })).toBeVisible();
});

test('M6/M7/M8 incident, policy evaluation and a budget exist', async () => {
  const attack = await api('POST', '/security/simulate-attack', {
    organization_id: orgId, attack_type: 'ddos', target_resource: vm.instance_id,
  });
  expect(attack.status).toBe(201);
  expect(attack.body.detections).toBeGreaterThanOrEqual(2); // the detector recognises the injected traffic
  const policy = await api('POST', '/governance/policies', {
    organization_id: orgId, name: `tags-${stamp}`, policy_rule: 'resource_type=vm;tag=owner:platform', status: 'active',
  });
  expect(policy.status).toBeLessThan(300);
  const check = await api('POST', '/governance/compliance/check', { organization_id: orgId });
  expect(check.status).toBeLessThan(300);
  const budget = await api('POST', '/cost/budgets', {
    organization_id: orgId, name: `b-${stamp}`, amount: 50, period: 'monthly', start_date: new Date().toISOString().slice(0, 10),
  });
  expect(budget.status).toBe(201);
});

test('M10 remediation: review, approve, execute and verify the resource changed', async () => {
  await page.goto('/remediation');
  await expect(page.getByRole('heading', { name: 'Remediation Agent' })).toBeVisible();
  const issue = page.getByRole('button', { name: /DDoS threat/ }).first();
  await expect(issue).toBeVisible();
  await issue.click();
  await expect(page.getByText('Isolate resource')).toBeVisible();
  await expect(page.getByText('Scale up capacity')).toBeVisible();
  await expect(page.getByRole('cell', { name: 't2.medium' }).first()).toBeVisible(); // before/after preview

  await shot('m10_plan');
  const execute = page.getByRole('button', { name: /Execute 2 actions/ });
  await expect(execute).toBeDisabled(); // approval required first
  await page.getByLabel(/approve these configuration changes/).check();
  await execute.click();
  await expect(page.getByText(/Issue status: Active → Resolved/)).toBeVisible();
  await expect(page.getByRole('cell', { name: 'Scale up' }).first()).toBeVisible(); // history row
  await shot('m10_result');

  const after = await api('GET', `/resources/vm?organization_id=${orgId}`);
  const changed = (after.body.data || after.body.vms).find((v) => v.id === vm.id);
  expect(changed.instance_type).toBe('t2.medium');
  const threats = await api('GET', `/security/threats?organization_id=${orgId}`);
  const list = threats.body.threats || threats.body.data || threats.body;
  expect(list.find((t) => t.affected_resources?.includes(vm.instance_id)).status).toBe('resolved');
});

test('M11 audit trail shows the remediation and is filterable', async () => {
  await page.goto('/audit');
  await page.getByLabel('Activity type').selectOption('remediation');
  await page.getByRole('button', { name: 'Apply filters' }).click();
  await expect(page.getByRole('button', { name: /Remediation executed/ })).toBeVisible();
  // Only remediation events remain — a stale unfiltered response must not overwrite the result.
  await expect(page.getByRole('button', { name: /Vm created|Budget created|Attack simulated/ })).toHaveCount(0);
  await page.getByRole('button', { name: /Remediation executed/ }).click();
  await expect(page.getByText(/"issue_status": "resolved"/)).toBeVisible();
  await shot('m11_timeline');
  await page.getByRole('button', { name: 'Clear' }).click(); // filters persist across tabs until cleared
  await page.getByRole('tab', { name: 'My account activity' }).click();
  await expect(page.getByRole('button', { name: /Settings updated/ }).first()).toBeVisible();
});

test('M9 reports still generate and are audited', async () => {
  await page.goto('/reports');
  const [csv] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Security Events (CSV)' }).click(),
  ]);
  expect(csv.suggestedFilename()).toMatch(/\.csv$/i);
  await expect.poll(async () => {
    const events = await api('GET', `/audit/events?organization_id=${orgId}&category=report`);
    return events.body.data.total;
  }).toBeGreaterThan(0);
});

test('alerts follow preferences and logout revokes the session', async () => {
  await page.goto('/');
  await page.getByRole('button', { name: /Alerts:/ }).click();
  await expect(page.getByText(/open policy violation/)).toBeVisible();
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: 'Log out' }).click();
  await expect(page).toHaveURL(/login/);
  const after = await page.request.get(`${API}/settings`, { headers: { Authorization: `Bearer ${token}` } });
  expect(after.status()).toBe(401); // the old access token no longer works
});

test('no uncaught browser exceptions during the scenario', async () => {
  expect(pageErrors).toEqual([]);
});
