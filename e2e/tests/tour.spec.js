const { test, expect } = require('@playwright/test');

const API = process.env.E2E_API_URL || 'http://localhost:5000/api';
const PASSWORD = 'Str0ng!Pass123';
const popover = (page) => page.locator('.driver-popover');
const title = (page) => page.locator('.driver-popover-title');
const progress = (page) => page.locator('.driver-popover-progress-text');

async function newUser(request, label) {
  const email = `tour_${label}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 5)}@example.com`;
  const res = await request.post(`${API}/auth/register`, {
    data: { email, password: PASSWORD, first_name: 'Tour', last_name: label },
  });
  expect(res.status()).toBe(201);
  return email;
}

async function login(page, email) {
  await page.goto('/login');
  await page.getByPlaceholder('you@example.com').fill(email);
  await page.getByPlaceholder('••••••••').fill(PASSWORD);
  await page.getByRole('button', { name: 'Sign In' }).click();
  await expect(page.getByRole('heading', { name: 'Resource Operations Dashboard' })).toBeVisible();
}

const next = (page) => page.locator('.driver-popover-next-btn, .driver-popover-done-btn').click();

test('new account is offered the tour once; steps, back, skip and persistence work', async ({ page, request }) => {
  const email = await newUser(request, 'a');
  await login(page, email);

  const welcome = page.getByRole('dialog', { name: /Welcome! Want a quick tour/ });
  await expect(welcome).toBeVisible();
  await page.getByTestId('tour-start').click();

  // Step 1 is a centred welcome; progress is shown as "Step X of N"
  await expect(title(page)).toHaveText('Welcome to the Cloud Simulator');
  await expect(progress(page)).toHaveText(/Step 1 of \d+/);

  await next(page);
  await expect(title(page)).toHaveText('Sidebar menu');
  await expect(page.locator('.driver-active-element')).toHaveAttribute('data-tour', 'nav');

  await next(page);
  await expect(title(page)).toHaveText('Dashboard');
  await page.locator('.driver-popover-prev-btn').click();
  await expect(title(page)).toHaveText('Sidebar menu');

  // Walk forward across routes until the Resources page is reached
  for (let i = 0; i < 4; i += 1) await next(page);
  await expect(page).toHaveURL(/\/resources$/);
  await expect(title(page)).toHaveText('Where the numbers come from');

  // The tour never performs actions: clicking the highlighted "Create VM" control does nothing
  await next(page);
  await expect(title(page)).toHaveText('Create a virtual machine');
  await page.locator('[data-tour="create-vm"]').click({ force: true });
  await expect(page.getByRole('heading', { name: 'Create Virtual Machine' })).toHaveCount(0);

  // Skip ends the tour, keeps the app usable and is remembered after a reload
  await page.getByTestId('tour-end').click();
  await expect(popover(page)).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Resources', level: 1 })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Resources', level: 1 })).toBeVisible();
  await expect(welcome).toHaveCount(0);
  await expect(popover(page)).toHaveCount(0);

  // Replay from Help starts again at step 1 and can run to the end
  await page.getByRole('button', { name: /Help: take a guided tour/ }).click();
  await expect(progress(page)).toHaveText(/Step 1 of (\d+)/);
  const total = Number((await progress(page).innerText()).match(/of (\d+)/)[1]);
  for (let i = 1; i < total; i += 1) await next(page);
  await expect(title(page)).toHaveText('Need this again?');
  await expect(page).toHaveURL(/\/reports$/);
  await page.locator('.driver-popover-done-btn').click();
  await expect(popover(page)).toHaveCount(0);
});

test('tour preference is stored per user, not per browser', async ({ page, request }) => {
  const first = await newUser(request, 'b1');
  const second = await newUser(request, 'b2');

  await login(page, first);
  await page.getByTestId('tour-skip-welcome').click();
  await page.getByRole('button', { name: 'Log out' }).click();

  await login(page, second);
  await expect(page.getByTestId('tour-start')).toBeVisible(); // second user still gets the offer
  await page.getByTestId('tour-skip-welcome').click();

  await page.getByRole('button', { name: 'Log out' }).click();
  await login(page, first);
  await expect(page.getByTestId('tour-start')).toHaveCount(0); // first user's dismissal remembered
});

test('existing (older) accounts are not forced through onboarding', async ({ page, request }) => {
  const email = await newUser(request, 'c');
  // Both responses that carry the user object report an old account.
  await page.route(/\/api\/auth\/(profile|login)$/, async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    const user = body.data?.user;
    if (user) user.created_at = '2025-01-01T00:00:00';
    await route.fulfill({ response, json: body });
  });
  await login(page, email);
  await page.waitForTimeout(1500);
  await expect(page.getByTestId('tour-start')).toHaveCount(0);
  await expect(popover(page)).toHaveCount(0);
  // ...but they can still start it manually
  await page.getByRole('button', { name: /Help: take a guided tour/ }).click();
  await expect(progress(page)).toHaveText(/Step 1 of/);
});

test('viewers do not see steps for controls they do not have', async ({ page, request }) => {
  const email = await newUser(request, 'd');
  await page.route('**/api/org/', async (route) => {
    if (route.request().method() !== 'GET') return route.continue();
    const response = await route.fetch();
    const text = JSON.stringify(await response.json()).replace(/"(my_role|role)":"owner"/g, '"$1":"viewer"');
    return route.fulfill({ response, body: text });
  });
  await login(page, email);
  await page.getByTestId('tour-start').click();
  const total = Number((await progress(page).innerText()).match(/of (\d+)/)[1]);
  expect(total).toBeLessThan(18); // owner sees 18 steps
  const seen = [];
  while (!(await page.locator('.driver-popover-done-btn').isVisible())) {
    await next(page);
    seen.push(await title(page).innerText());
  }
  expect(seen.at(-1)).toBe('Need this again?');
  expect(seen).not.toContain('Create a virtual machine');
  expect(seen).not.toContain('Practise an attack');
  expect(seen).not.toContain('Set a budget');
});

test('mobile layout: no sideways scroll, menu opens, tour opens the sidebar for its step', async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  const email = await newUser(request, 'e');
  await login(page, email);
  await page.getByTestId('tour-start').click();
  await next(page); // sidebar step
  await expect(title(page)).toHaveText('Sidebar menu');
  await expect(page.locator('[data-tour="nav"]')).toBeInViewport();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await page.getByTestId('tour-end').click();
  await expect(page.getByRole('button', { name: 'Open navigation menu' })).toBeVisible();
});
