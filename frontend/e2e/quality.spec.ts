import { test, expect } from '@playwright/test'

test.describe('واجهة Qentry', () => {
  test('login page renders Arabic RTL layout', async ({ page }) => {
    await page.goto('/auth/login')
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl')
    await expect(page.getByRole('heading').first()).toBeVisible()
    await expect(page.locator('input').first()).toBeVisible()
  })

  test('mobile viewport does not overflow horizontally', async ({ page }) => {
    await page.goto('/auth/login')
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
    expect(overflow).toBe(false)
  })

  test('light theme keeps the sign-in surface readable', async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('qentry.admin.theme', 'light'))
    await page.goto('/auth/login')

    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
    const cardBackground = await page.locator('.auth-card').evaluate((node) => getComputedStyle(node).backgroundColor)
    const inputBackground = await page.locator('.field__input').first().evaluate((node) => getComputedStyle(node).backgroundColor)

    expect(cardBackground).not.toBe('rgba(30, 41, 59, 0.6)')
    expect(inputBackground).not.toBe('rgba(15, 23, 42, 0.7)')
  })

})
