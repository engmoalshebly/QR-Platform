import { test as base, expect } from '@playwright/test'

const test = base.extend({
  browser: [async ({ playwright }, use) => {
    const browser = process.env.PLAYWRIGHT_CDP_URL
      ? await playwright.chromium.connectOverCDP(process.env.PLAYWRIGHT_CDP_URL)
      : await playwright.chromium.launch()
    await use(browser)
    await browser.close()
  }, { scope: 'worker' }],
})

import { getApiErrorMessage, getApiErrorCode } from '../src/services/http/apiErrors'

test('API error messages support structured limits and legacy text', () => {
  const error = (detail: unknown) => ({ response: { status: 429, data: { detail } } })
  const results = {
    plan: getApiErrorMessage(error({ code: 'PLAN_LIMIT_EXCEEDED', message: 'وصلت إلى حد الفعاليات' })),
    planCode: getApiErrorCode(error({ code: 'PLAN_LIMIT_EXCEEDED', message: 'وصلت إلى حد الفعاليات' })),
    rateCode: getApiErrorCode(error({ code: 'RATE_LIMIT_EXCEEDED', message: 'حاول لاحقاً' })),
    legacy: getApiErrorMessage(error('رسالة قديمة')),
    legacyCode: getApiErrorCode(error('رسالة قديمة')),
    fields: getApiErrorMessage(error({ message: 'تحقق من البيانات', fields: ['رقم الهاتف'], issues: ['قيمة غير صحيحة'] })),
    fallback: getApiErrorMessage(error({ code: 'FUTURE_ERROR' }), 'تعذر تنفيذ الطلب'),
    unknownCode: getApiErrorCode(error({ code: 'FUTURE_ERROR' })),
  }
  expect(results.plan).toBe('وصلت إلى حد الفعاليات')
  expect(results.planCode).toBe('PLAN_LIMIT_EXCEEDED')
  expect(results.rateCode).toBe('RATE_LIMIT_EXCEEDED')
  expect(results.legacy).toBe('رسالة قديمة')
  expect(results.legacyCode).toBeUndefined()
  expect(results.fields).toContain('رقم الهاتف')
  expect(results.fields).toContain('قيمة غير صحيحة')
  expect(results.fallback).toBe('تعذر تنفيذ الطلب')
  expect(results.unknownCode).toBeUndefined()
})

test('login displays a structured throttle message without rendering its object', async ({ page }) => {
  await page.route('**/api/v1/auth/login', route => route.fulfill({
    status: 429,
    contentType: 'application/json',
    headers: { 'Retry-After': '60' },
    body: JSON.stringify({ detail: { code: 'RATE_LIMIT_EXCEEDED', message: 'تم تجاوز حد الطلبات. حاول لاحقاً.', retry_after: 60 } }),
  }))
  await page.goto('/auth/login')
  await page.locator('input[type="email"]').fill('operator@example.test')
  await page.locator('input[type="password"]').fill('password-for-test')
  await page.locator('button[type="submit"]').click()
  await expect(page.getByText('تم تجاوز حد الطلبات. حاول لاحقاً.', { exact: true })).toBeVisible()
  await expect(page.getByText('[object Object]', { exact: true })).toHaveCount(0)
})

test('limit rejection preserves the draft and gates plan action by permission', async ({ page }) => {
  await page.route('**/api/v1/events', route => route.fulfill({ status: 429, contentType: 'application/json',
    body: JSON.stringify({ detail: { code: 'PLAN_LIMIT_EXCEEDED', limit_key: 'events_per_month', current: 1, limit: 1,
      requested: 1, resets_at: '2026-11-01T00:00:00+00:00', message: 'وصلت إلى حد الفعاليات' } }),
  }))
  await page.goto('/auth/login')
  await page.evaluate(async () => {
    const path = '/e2e/fixtures/limit-notice-harness.tsx'
    const { mountEventDraft } = await import(path)
    mountEventDraft()
  })
  await page.locator('#ev-title').fill('فعالية محفوظة في النموذج')
  await page.locator('input[type="datetime-local"]').fill('2026-11-01T10:00')
  await page.locator('button[type="submit"]').click()
  await expect(page.getByText('وصلت إلى حد الفعاليات', { exact: true })).toBeVisible()
  await expect(page.locator('#ev-title')).toHaveValue('فعالية محفوظة في النموذج')
  await expect(page.getByRole('button', { name: 'عرض الباقات', exact: true })).toBeVisible()
  await expect(page.getByText(/يتجدد الرصيد في/)).toBeVisible()
  await page.evaluate(async () => {
    const path = '/e2e/fixtures/limit-notice-harness.tsx'
    const { setRole } = await import(path)
    setRole('member')
  })
  await expect(page.getByRole('button', { name: 'عرض الباقات', exact: true })).toHaveCount(0)
  await expect(page.getByText('تواصل مع مسؤول الحساب لإدارة الاشتراك أو السعة المتاحة.')).toBeVisible()
  await expect(page.locator('#ev-title')).toHaveValue('فعالية محفوظة في النموذج')
})


test('request throttle waits before allowing retry and never offers plans', async ({ page }) => {
  await page.goto('/auth/login')
  await page.evaluate(async () => {
    const path = '/e2e/fixtures/limit-notice-harness.tsx'
    const { mountNotice } = await import(path)
    mountNotice({ code: 'RATE_LIMIT_EXCEEDED', message: 'انتظر ثم أعد المحاولة', retry_after: 2 })
  })
  await expect(page.getByRole('button', { name: 'إعادة المحاولة', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'عرض الباقات', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'إعادة المحاولة', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: 'إعادة المحاولة', exact: true }).click()
  await expect(page.locator('#notice-harness')).toHaveAttribute('data-retried', 'true')
})

test('event quota offers event management instead of a plan upgrade', async ({ page }) => {
  await page.goto('/auth/login')
  await page.evaluate(async () => {
    const path = '/e2e/fixtures/limit-notice-harness.tsx'
    const { mountNotice } = await import(path)
    mountNotice({ code: 'EVENT_QUOTA_EXCEEDED', message: 'حصة الفعالية ممتلئة', event_id: 'test-event', current: 4, limit: 4, requested: 1 })
  })
  await expect(page.getByRole('link', { name: /إدارة حصة الفعالية/ })).toHaveAttribute('href', '/events/test-event?tab=overview')
  await expect(page.getByRole('button', { name: 'عرض الباقات', exact: true })).toHaveCount(0)
})
