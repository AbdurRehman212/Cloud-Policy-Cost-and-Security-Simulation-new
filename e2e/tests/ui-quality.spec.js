const fs = require('fs');
const { test, expect } = require('@playwright/test');
const AxeBuilder = require('@axe-core/playwright').default;

// Responsive + accessibility sweep over the main pages (WCAG 2.2 AA target).
// Set E2E_SHOTS=<dir> to also save a screenshot per page/width for manual visual review.
const API = process.env.E2E_API_URL || 'http://localhost:5000/api';
const PASSWORD = 'Str0ng!Pass123';
const PAGES = ['/', '/resources', '/security', '/governance', '/cost', '/reports', '/organization', '/membership', '/settings', '/profile'];
const WIDTHS = [390, 768, 1024, 1440];
const BLOCKING = ['critical', 'serious'];

let page;
const findings = [];

test.beforeAll(async ({ browser, request }) => {
  const email = `ui_${Date.now().toString(36)}@example.com`;
  await request.post(`${API}/auth/register`, { data: { email, password: PASSWORD, first_name: 'Ui', last_name: 'Check' } });
  page = await (await browser.newContext()).newPage();
  await page.goto('/login');
  await page.getByPlaceholder('you@example.com').fill(email);
  await page.getByPlaceholder('••••••••').fill(PASSWORD);
  await page.getByRole('button', { name: 'Sign In' }).click();
  await expect(page.getByRole('heading', { name: 'Resource Operations Dashboard' })).toBeVisible();
  await page.getByTestId('tour-skip-welcome').click();
});

for (const width of WIDTHS) {
  test(`no overflow, duplicate ids or serious a11y violations at ${width}px`, async () => {
    await page.setViewportSize({ width, height: 900 });
    for (const path of PAGES) {
      await page.goto(path);
      await page.waitForLoadState('networkidle');
      await page.waitForTimeout(600);

      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      const dupes = await page.evaluate(() => {
        const seen = {};
        document.querySelectorAll('[id]').forEach((el) => { seen[el.id] = (seen[el.id] || 0) + 1; });
        return Object.keys(seen).filter((id) => seen[id] > 1);
      });
      const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze();
      const bad = axe.violations.filter((v) => BLOCKING.includes(v.impact));
      findings.push({ width, path, overflow, dupes, axe: bad.map((v) => `${v.id}(${v.nodes.length})`) });
      if (process.env.E2E_SHOTS) await page.screenshot({ path: `${process.env.E2E_SHOTS}/${width}${path.replace(/\//g, '_') || '_home'}.png` });

      expect.soft(overflow, `${path} @${width} horizontal overflow`).toBeLessThanOrEqual(1);
      expect.soft(dupes, `${path} @${width} duplicate ids`).toEqual([]);
      expect.soft(bad.map((v) => `${v.id}(${v.nodes.length})`), `${path} @${width} axe`).toEqual([]);
    }
  });
}

test.afterAll(() => {
  if (process.env.E2E_REPORT) fs.writeFileSync(process.env.E2E_REPORT, JSON.stringify(findings, null, 1));
});

test('keyboard: first Tab reaches the skip link and it moves focus to the main content', async () => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto('/resources');
  await page.waitForLoadState('networkidle');
  await page.keyboard.press('Tab');
  const skip = page.getByRole('link', { name: 'Skip to main content' });
  await expect(skip).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('#main-content')).toBeFocused();
});

test('form controls are programmatically labelled (sign-in and register)', async ({ browser }) => {
  const anon = await (await browser.newContext()).newPage();
  await anon.goto('/login');
  await expect(anon.getByLabel('Email Address')).toBeVisible();
  await expect(anon.getByLabel('Password')).toBeVisible();
  await anon.goto('/register');
  for (const name of ['First Name', 'Last Name', 'Email Address']) await expect(anon.getByLabel(name)).toBeVisible();
});
