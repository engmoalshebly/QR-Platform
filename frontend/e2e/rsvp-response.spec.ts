import { test, expect } from '@playwright/test'

test('RSVP failure preserves pending invitation and guest can retry successfully', async ({ page }) => {
  await page.route('**/api/v1/invitations/view/rsvp-demo', route => route.fulfill({
    contentType: 'application/json', body: JSON.stringify({
      token: 'rsvp-demo', event_title: 'حفل تجريبي', guest_name: 'ضيف تجريبي',
      ticket_class: 'normal', status: 'created', rsvp_status: 'pending',
      metadata: { require_rsvp: true }, allow_rsvp: true, allow_plus_one: false,
      start_date: '2026-10-30T15:00:00Z',
    }),
  }))
  let attempts = 0
  await page.route('**/api/v1/invitations/rsvp/rsvp-demo', route => {
    attempts++
    return route.fulfill({ status: attempts === 1 ? 503 : 200, contentType: 'application/json',
      body: JSON.stringify(attempts === 1 ? { detail: 'لم يتم حفظ ردك، حاول مجدداً' } : { rsvp_status: 'accepted' }) })
  })
  await page.goto('/i/rsvp-demo')
  await expect(page.getByText('أظهر هذا الرمز عند الدخول')).toHaveCount(0)
  await page.getByRole('button', { name: 'نعم، سأحضر' }).click()
  await expect(page.getByRole('alert')).toHaveText('لم يتم حفظ ردك، حاول مجدداً')
  await expect(page.getByText('أظهر هذا الرمز عند الدخول')).toHaveCount(0)
  await page.getByRole('button', { name: 'نعم، سأحضر' }).click()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByText('أظهر هذا الرمز عند الدخول')).toBeVisible()
  expect(attempts).toBe(2)
})
