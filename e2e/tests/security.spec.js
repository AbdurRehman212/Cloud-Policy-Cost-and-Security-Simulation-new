// Security regressions found in the final hardening pass.
const { test, expect } = require('@playwright/test');

const API = process.env.E2E_API_URL || 'http://localhost:5000/api';
const PASSWORD = 'Str0ng!Pass123';

test('login ignores an off-site ?redirect= target (open redirect)', async ({ page, request }) => {
  const email = `sec_${Date.now().toString(36)}@example.com`;
  const reg = await request.post(`${API}/auth/register`, {
    data: { email, password: PASSWORD, first_name: 'Sec', last_name: 'Test' },
  });
  expect(reg.status()).toBe(201);
  await page.goto('/login?redirect=' + encodeURIComponent('/\\evil.example/steal'));
  await page.getByPlaceholder('you@example.com').fill(email);
  await page.getByPlaceholder('••••••••').fill(PASSWORD);
  await page.getByRole('button', { name: 'Sign In' }).click();
  await expect(page.getByRole('heading', { name: 'Resource Operations Dashboard' })).toBeVisible();
  expect(new URL(page.url()).hostname).toBe('localhost'); // still on this site
  expect(page.url()).not.toContain('evil.example');
});

test('API responses carry security headers', async ({ request }) => {
  const res = await request.post(`${API}/auth/login`, { data: { email: 'nobody@example.com', password: 'x' } });
  expect(res.headers()['x-content-type-options']).toBe('nosniff');
  expect(res.headers()['x-frame-options']).toBe('DENY');
  expect(res.headers()['cache-control']).toBe('no-store');
});
