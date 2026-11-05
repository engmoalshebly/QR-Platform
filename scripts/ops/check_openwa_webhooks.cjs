// Read-only regression: real webhooks and legacy/invalid provider payloads.
const { chromium, expect } = require('../../frontend/node_modules/@playwright/test');
const fs = require('fs');
const credentials = JSON.parse(fs.readFileSync(process.env.OPENWA_DASHBOARD_CREDENTIALS || '/home/alrazi/.qentry/openwa-dashboard-admin.json', 'utf8'));
const base = process.env.OPENWA_DASHBOARD_ORIGIN || 'https://notify.prideidea.com';
(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const variant of ['live', 'array', 'json-string', 'invalid']) {
      const context = await browser.newContext({ ignoreHTTPSErrors: process.env.OPENWA_TEST_ORIGIN_DIRECT === '1' });
      try {
        await context.addInitScript(key => {
          sessionStorage.setItem('openwa_api_key', key);
          localStorage.setItem('i18nextLng', 'en');
        }, credentials.api_key);
        const page = await context.newPage();
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        if (variant !== 'live') {
          await page.route('**/api/webhooks', route => route.fulfill({ json: [{
            id: '11111111-1111-4111-8111-111111111111',
            sessionId: '22222222-2222-4222-8222-222222222222',
            url: 'https://example.com/receipt', active: true,
            events: variant === 'array' ? ['message.ack'] : variant === 'json-string' ? '["message.ack"]' : 'not-json',
            createdAt: '2026-10-20T00:00:00Z', updatedAt: '2026-10-20T00:00:00Z',
          }] }));
        }
        await page.goto(base + '/dashboard#/webhooks');
        await expect(page.locator('.webhooks-content')).toBeVisible();
        if (variant === 'invalid') {
          await expect(page.getByRole('alert')).toContainText('Invalid webhook events');
        } else {
          await expect(page.locator('.events-cell').first()).toContainText('message.ack');
          await page.getByRole('button', { name: 'Edit', exact: true }).first().click();
          await expect(page.getByRole('heading', { name: 'Edit Webhook', exact: true })).toBeVisible();
          await expect(page.locator('.modal .event-tag.selected')).toContainText(['message.ack']);
          await page.locator('.modal-footer').getByRole('button', { name: 'Cancel', exact: true }).click();
        }
        await expect(page.getByText('Something went wrong', { exact: true })).toHaveCount(0);
        if (errors.length) throw new Error('Unexpected browser exception');
        console.log(variant + ': passed');
      } finally { await context.close(); }
    }
  } finally { await browser.close(); }
})().catch(error => {
  console.error(String(error.message).replaceAll(credentials.api_key, '[REDACTED]').slice(0, 1400));
  process.exitCode = 1;
});
