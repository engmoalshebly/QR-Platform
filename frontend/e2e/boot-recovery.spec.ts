import { test, expect } from '@playwright/test'

test('stalled application download shows loading and offers recovery', async ({ page }) => {
  await page.route('**/src/main.tsx', async route => {
    await new Promise(resolve => setTimeout(resolve, 25000))
    await route.abort()
  })
  await page.goto('/users', { waitUntil: 'commit' })
  await expect(page.getByText('جار تحميل الصفحة…', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'إعادة تحميل الصفحة' })).toBeVisible({ timeout: 20000 })
})

test('unavailable optional font stylesheet does not block login', async ({ page }) => {
  await page.route('**/fonts/google/fonts.css', route => route.abort())
  await page.goto('/users')
  await expect(page.getByRole('button', { name: 'تسجيل الدخول', exact: true })).toBeVisible()
  await expect(page.locator('#app-boot-status')).toHaveCount(0)
})
