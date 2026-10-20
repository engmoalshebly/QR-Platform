import { test, expect } from '@playwright/test'

const email = 'invited@example.test'
const password = 'Aa9!random-initial-password-for-test'

test('invited user gets credentials directly and login email is prefilled', async ({ page }) => {
  let activations = 0
  await page.route('**/api/v1/invites/accept/test-token/activate', async route => {
    expect(route.request().method()).toBe('POST')
    activations++
    await route.fulfill({ status: 201, contentType: 'application/json', headers: { 'Cache-Control': 'no-store' },
      body: JSON.stringify({ email, initial_password: password, tenant_id: 'test-tenant', role: 'member' }) })
  })
  await page.goto('/invites/accept/test-token')
  expect(activations).toBe(0)
  await expect(page.getByText('اسم المؤسسة', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'قبول الدعوة وإنشاء حسابي', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'تم إنشاء حسابك والانضمام' })).toBeVisible()
  await expect(page.getByLabel('البريد الإلكتروني', { exact: true })).toHaveValue(email)
  await expect(page.getByLabel('كلمة المرور الأولية', { exact: true })).toHaveValue(password)
  await expect(page.getByLabel('كلمة المرور الأولية', { exact: true })).toHaveAttribute('type', 'password')
  await page.getByRole('button', { name: 'إظهار كلمة المرور', exact: true }).click()
  await expect(page.getByLabel('كلمة المرور الأولية', { exact: true })).toHaveAttribute('type', 'text')
  const storage = await page.evaluate(() => JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } }))
  expect(storage).not.toContain(password)
  expect(page.url()).not.toContain(password)
  expect(activations).toBe(1)
  await page.getByRole('link', { name: 'تسجيل الدخول بحسابي' }).click()
  await expect(page.locator('input[type="email"]')).toHaveValue(email)
  await expect(page.locator('input[type="password"]')).toBeEmpty()
})

for (const code of ['INVITE_ACCOUNT_EXISTS', 'INVITE_ALREADY_ACCEPTED']) {
  test(`${code} offers login/reset without new credentials`, async ({ page }) => {
    await page.route('**/api/v1/invites/accept/test-token/activate', route => route.fulfill({
      status: 409, contentType: 'application/json',
      body: JSON.stringify({ detail: { code, email, message: 'سجّل الدخول بكلمة مرورك الحالية.' } }),
    }))
    await page.goto('/invites/accept/test-token')
    await page.getByRole('button', { name: 'قبول الدعوة وإنشاء حسابي' }).click()
    await expect(page.getByRole('alert')).toHaveText('سجّل الدخول بكلمة مرورك الحالية.')
    await expect(page.getByLabel('كلمة المرور الأولية', { exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'قبول الدعوة وإنشاء حسابي' })).toHaveCount(0)
    await expect(page.getByRole('link', { name: 'نسيت كلمة المرور', exact: true })).toBeVisible()
    const href = await page.getByRole('link', { name: 'لدي حساب بالفعل — تسجيل الدخول' }).getAttribute('href')
    expect(href).toContain(encodeURIComponent(email))
    if (code === 'INVITE_ALREADY_ACCEPTED') expect(href).not.toContain('invite=')
    else expect(href).toContain('invite=test-token')
  })
}
