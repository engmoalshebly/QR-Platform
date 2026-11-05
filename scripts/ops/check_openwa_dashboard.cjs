// Live UI verification. Creates and deletes only its own temporary session.
// No messages are sent and no phone is paired. Secrets are never printed.
const { chromium, expect } = require('../../frontend/node_modules/@playwright/test');
const fs = require('fs');
const credentials = JSON.parse(fs.readFileSync(process.env.OPENWA_DASHBOARD_CREDENTIALS || '/home/alrazi/.qentry/openwa-dashboard-admin.json', 'utf8'));
const base = process.env.OPENWA_DASHBOARD_ORIGIN || 'https://notify.prideidea.com';
const ui = base + '/dashboard';
(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ locale: 'en-US', ignoreHTTPSErrors: process.env.OPENWA_TEST_ORIGIN_DIRECT === '1' });
  const page = await context.newPage();
  const errors = [];
  const sockets = [];
  let subscribed = false;
  let temporaryId;
  page.on('pageerror', error => errors.push(error.message));
  page.on('websocket', ws => {
    sockets.push(ws.url());
    ws.on('framereceived', frame => {
      if (String(frame.payload).includes('"type":"subscribed"')) subscribed = true;
    });
  });
  const api = async (path, options = {}) => {
    const response = await context.request.fetch(base + '/api' + path,
      { ...options, headers: { 'X-API-Key': credentials.api_key } });
    if (!response.ok()) throw new Error(`API status ${response.status()}`);
    return response.status() === 204 ? null : response.json();
  };
  try {
    await page.addInitScript(() => localStorage.setItem('i18nextLng', 'en'));
    await page.goto(ui);
    await page.locator('#apiKey').fill('invalid-ui-verification-key');
    await page.locator('button.connect-btn').click();
    await expect(page.locator('.error-message')).toBeVisible();
    await page.locator('#apiKey').fill(credentials.api_key);
    await page.locator('button.connect-btn').click();
    await expect(page.locator('.sidebar')).toBeVisible();
    await page.goto(ui + '#/sessions');
    await expect(page.locator('.sessions-page')).toBeVisible();
    const name = 'ui-verification-' + Date.now();
    await page.getByRole('button', { name: 'New Session', exact: true }).click();
    await page.locator('.modal-body input').fill(name);
    const created = page.waitForResponse(r => r.url().endsWith('/api/sessions') && r.request().method() === 'POST');
    await page.locator('.modal-footer').getByRole('button', { name: 'Create', exact: true }).click();
    const response = await created;
    if (!response.ok()) throw new Error('Session creation failed');
    temporaryId = (await response.json()).id;
    const card = page.locator('.session-card').filter({ hasText: name });
    await expect(card).toBeVisible();
    await card.getByRole('button', { name: 'Start', exact: true }).click();
    await expect(page.locator('.qr-modal img')).toBeVisible({ timeout: 90000 });
    const src = await page.locator('.qr-modal img').getAttribute('src');
    if (!src.startsWith('data:image/')) throw new Error('QR image is not available');
    await expect.poll(() => subscribed, { timeout: 30000 }).toBe(true);
    if (sockets.some(url => url.includes('apiKey') || url.includes(credentials.api_key))) throw new Error('Credential in WebSocket URL');
    if (errors.length) throw new Error('Browser page errors detected');
    await page.setViewportSize({ width: 390, height: 844 });
    if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)) throw new Error('Mobile page overflow');
    console.log(JSON.stringify({ login: true, invalid_key_rejected: true, sessions: true,
      temporary_session_created: true, qr_image: true, websocket_subscription: true,
      websocket_url_contains_key: false, browser_errors: 0, mobile_overflow: false }));
  } finally {
    if (temporaryId) { await api('/sessions/' + temporaryId, { method: 'DELETE' }); console.log('Temporary session deleted'); }
    await context.close();
    await browser.close();
  }
})().catch(error => { console.error(String(error.message).replaceAll(credentials.api_key, '[REDACTED]').slice(0, 1600)); process.exitCode = 1; });
