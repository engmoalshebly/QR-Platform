import { test, expect } from '@playwright/test'

test.describe('Team Manager workflow', () => {
  test('login entry is available in Arabic RTL', async ({ page }) => {
    await page.goto('/auth/login')
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl')
    await expect(page.getByRole('heading').first()).toBeVisible()
  })

  test('full workflow contract', async ({ page }) => {
    test.skip(!process.env.E2E_TEAM_MANAGER_EMAIL, 'Set E2E_TEAM_MANAGER_EMAIL/PASSWORD to run authenticated workflow')
    await page.goto('/auth/login')
    await page.getByLabel(/البريد|email/i).fill(process.env.E2E_TEAM_MANAGER_EMAIL!)
    await page.getByLabel(/كلمة المرور|password/i).fill(process.env.E2E_TEAM_MANAGER_PASSWORD!)
    await page.getByRole('button', { name: /دخول|login/i }).click()
    await expect(page).toHaveURL(/teams|dashboard/)
    await page.goto('/teams?tab=requests')
    await expect(page).toHaveURL(/teams\?tab=requests/)
    // The remaining workflow mutations are intentionally API-authorized and
    // should be exercised by the backend integration suite with seeded data.
  })
})
