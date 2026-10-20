import { test, expect } from '@playwright/test'

test('storage downloads never receive workspace credentials', async ({ page }) => {
  let requested = false
  await page.route('https://supdawaa.prideidea.com/storage/v1/object/public/check.pdf', async route => {
    const headers = route.request().headers()
    expect(headers.authorization).toBeUndefined()
    expect(headers['x-tenant-id']).toBeUndefined()
    expect(headers.cookie).toBeUndefined()
    requested = true
    await route.fulfill({ status: 200, contentType: 'application/pdf', headers: { 'Access-Control-Allow-Origin': '*' }, body: '%PDF-1.4' })
  })
  await page.goto('/auth/login')
  const download = page.waitForEvent('download')
  await page.evaluate(async () => {
    const path = '/src/services/http/client.ts'
    const { downloadAuthenticatedFile, setAccessToken } = await import(/* @vite-ignore */ path)
    setAccessToken('private-platform-token')
    sessionStorage.setItem('qentry_tenant_id', 'private-workspace')
    await downloadAuthenticatedFile('https://supdawaa.prideidea.com/storage/v1/object/public/check.pdf', 'check.pdf')
  })
  expect((await download).suggestedFilename()).toBe('check.pdf')
  expect(requested).toBe(true)
})
