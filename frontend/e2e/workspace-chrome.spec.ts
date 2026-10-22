import { test, expect } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    const json = path.endsWith('/events/preview')
      ? { id: 'preview', title: 'ملتقى شركاء النجاح', status: 'draft', start_date: '2026-11-15T17:00:00Z', end_date: null, vip_quota: 500, normal_quota: 2000, slug: 'partners', location: 'الرياض' }
      : path.endsWith('/stats') ? { total_invitations: 1250, accepted_count: 1050, declined_count: 50, checked_in_count: 720, vip_count: 250, normal_count: 1000 }
      : path.endsWith('/availability') ? { enabled: true }
      : path.includes('notifications') ? { count: 0 }
      : path.includes('subscription') ? {} : []
    await route.fulfill({ json })
  })
  await page.goto('/auth/login')
  await page.evaluate(async () => {
    const path = '/e2e/fixtures/workspace-chrome-harness.tsx'
    const { mountWorkspaceChrome } = await import(/* @vite-ignore */ path)
    mountWorkspaceChrome()
  })
  await expect(page.locator('.dash-header h1')).toHaveText('ملتقى شركاء النجاح')
})

test('navigation is compact and usable across screen sizes and themes', async ({ page }, testInfo) => {
  const mobile = testInfo.project.name === 'mobile'
  const sidebar = page.locator('#workspace-navigation')
  if (mobile) {
    await expect(sidebar).not.toBeVisible()
    await page.getByRole('button', { name: 'فتح القائمة الرئيسية' }).click()
    await expect(sidebar).toBeVisible()
    await expect(page.locator('.dash-main')).toHaveJSProperty('inert', true)
    await page.keyboard.press('Escape')
    await expect(sidebar).not.toBeVisible()
    await expect(page.getByRole('button', { name: 'فتح القائمة الرئيسية' })).toBeFocused()
    await expect(page.locator('.dash-main')).toHaveJSProperty('inert', false)
  } else {
    await expect(sidebar).toBeVisible()
    await expect(sidebar.getByRole('link', { name: 'الاشتراك والاستخدام' })).toBeVisible()
    await expect(sidebar.getByRole('link', { name: 'WhatsApp' })).toBeVisible()
    await page.getByRole('button', { name: 'تصغير القائمة الجانبية' }).click()
    await expect(sidebar).toHaveClass(/collapsed/)
    expect((await sidebar.boundingBox())!.width).toBeLessThan(80)
    await expect(sidebar.locator('.dash-brand__symbol img')).toBeVisible()
    await page.getByRole('button', { name: 'توسيع القائمة الجانبية' }).click()
  }
  await page.getByRole('button', { name: 'تفعيل الوضع الفاتح' }).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
  const geometry = await page.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth, boxes: Array.from(document.querySelectorAll('.dashboard-shell, .dash-main, .dash-header, .event-tabs')).map(el => ({ name: el.className, x: el.getBoundingClientRect().x, width: el.getBoundingClientRect().width })) }))
  expect(geometry.scroll, JSON.stringify(geometry)).toBe(geometry.width)
  await page.screenshot({ path: `/tmp/dawaa-workspace-${testInfo.project.name}-light.png`, fullPage: true })
  await page.getByRole('button', { name: 'تفعيل الوضع الداكن' }).click()
  await page.screenshot({ path: `/tmp/dawaa-workspace-${testInfo.project.name}-dark.png`, fullPage: true })
})

test('occasion tabs support keyboard selection and can be hidden', async ({ page }) => {
  const tabs = page.getByRole('tablist', { name: 'أقسام المناسبة' })
  await expect(tabs).toBeVisible()
  await page.getByRole('tab', { name: 'الإحصائيات', exact: true }).focus()
  await page.keyboard.press('ArrowLeft')
  await expect(page.getByRole('tab', { name: 'إعدادات المناسبة', exact: true })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('tabpanel', { name: 'إعدادات المناسبة', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'إخفاء تبويبات المناسبة' }).click()
  await expect(tabs).not.toBeVisible()
  await page.getByRole('button', { name: 'إظهار تبويبات المناسبة' }).click()
  await expect(tabs).toBeVisible()
})
