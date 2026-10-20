import { test, expect } from '@playwright/test'

test('reload waits for one cookie refresh before concurrent protected requests', async ({ page }) => {
  let refreshes = 0
  let protectedRequests = 0
  await page.route('**/api/v1/**', async route => {
    if (route.request().url().endsWith('/auth/refresh')) {
      refreshes++
      await new Promise(resolve => setTimeout(resolve, 150))
      await route.fulfill({ json: { access_token: 'restored-token' } })
    } else {
      expect(route.request().headers().authorization).toBe('Bearer restored-token')
      protectedRequests++
      await route.fulfill({ json: {} })
    }
  })
  await page.goto('/auth/login')
  await page.evaluate(async () => {
    sessionStorage.setItem('qentry-auth', JSON.stringify({ state: { user: { id: 'test' } } }))
    const path = '/src/services/http/client.ts'
    const { http, setAccessToken } = await import(/* @vite-ignore */ path)
    setAccessToken(null)
    await Promise.all(['/auth/me', '/invites', '/tenants/current/members', '/subscriptions/status', '/notifications/unread-count'].map(url => http.get(url)))
  })
  expect(refreshes).toBe(1)
  expect(protectedRequests).toBe(5)
})

test('simultaneous expired tokens share a refresh and retry with the renewed token', async ({ page }) => {
  let refreshes = 0
  let successes = 0
  await page.route('**/api/v1/**', async route => {
    if (route.request().url().endsWith('/auth/refresh')) {
      refreshes++
      await new Promise(resolve => setTimeout(resolve, 150))
      await route.fulfill({ json: { access_token: 'renewed-token' } })
    } else if (route.request().headers().authorization === 'Bearer expired-token') {
      await route.fulfill({ status: 401, json: { detail: 'Expired' } })
    } else {
      expect(route.request().headers().authorization).toBe('Bearer renewed-token')
      successes++
      await route.fulfill({ json: {} })
    }
  })
  await page.goto('/auth/login')
  await page.evaluate(async () => {
    const path = '/src/services/http/client.ts'
    const { http, setAccessToken } = await import(/* @vite-ignore */ path)
    setAccessToken('expired-token')
    await Promise.all(['/auth/me', '/invites', '/tenants/current/members'].map(url => http.get(url)))
  })
  expect(refreshes).toBe(1)
  expect(successes).toBe(3)
})
