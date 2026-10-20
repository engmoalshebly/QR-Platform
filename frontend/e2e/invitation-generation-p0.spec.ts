import { test, expect } from '@playwright/test'

const designedProbe = async (page: any, capabilities: { enabled: boolean }) => {
  await page.route('**/api/v1/generation-operations/capabilities', (route: any) => route.fulfill({
    json: { contract_version: 1, enabled: capabilities.enabled, max_cards: 1000, max_people_per_card: 100, output_formats: ['pdf', 'zip'] },
  }))
  await page.goto('/auth/login')
  return page.evaluate(async () => {
    const harnessPath = '/e2e/generation-hook-harness.tsx'
    const { mountDesignProbe } = await import(/* @vite-ignore */ harnessPath)
    let error: any = null
    const state = new Proxy({
      designTemplateId: 'test-template', designTicketClass: 'normal', requireRsvp: true,
      designExcelRows: [{ 'اسم الضيف': 'ضيف اختبار', 'رقم الجوال': '+967700000000', 'عدد الأشخاص': 3 }],
      dynamicFields: [{ data_key: 'guest.name', label: 'اسم الضيف' }],
      designColumnMapping: { 'guest.name': 'اسم الضيف' }, designedLayout: {}, canExport: false,
    }, { get(target, key) {
      if (key === 'setLocalError') return (value: any) => { error = value?.message || value }
      if (String(key).startsWith('set')) return () => {}
      return Reflect.get(target, key)
    } })
    const { api, unmount } = await mountDesignProbe(state, { id: 'test-event' })
    await api.handleGenerateDesignedFromExcel()
    unmount()
    return error
  })
}

test('designed RSVP keeps contacts independent of printed template fields', async ({ page }) => {
  let payload: any
  await page.route('**/api/v1/batches/generate-designed-fast', async route => {
    payload = route.request().postDataJSON()
    await route.fulfill({ json: { id: 'test-batch', status: 'queued' } })
  })
  const error = await designedProbe(page, { enabled: false })
  expect(error).toBeNull()
  expect(payload.invitations[0].guest_count).toBe(3)
  expect(payload.invitations[0].metadata.custom_fields['رقم الجوال']).toBe('+967700000000')
  expect(payload.invitations[0].metadata.require_rsvp).toBe(true)
  expect(payload.output_formats).toEqual([])
})

test('designed generation uses the durable 202 contract with one stable Idempotency-Key when enabled', async ({ page }) => {
  const keys: string[] = []
  let payload: any
  let legacyCalled = false
  await page.route('**/api/v1/batches/generate-designed-fast', async route => { legacyCalled = true; await route.fulfill({ status: 500, json: {} }) })
  await page.route('**/api/v1/generation-operations', async route => {
    if (route.request().method() !== 'POST') return route.fallback()
    keys.push(route.request().headers()['idempotency-key'])
    payload = route.request().postDataJSON()
    await route.fulfill({ status: 202, json: { id: 'op-1', status: 'queued', cards_count: 1, people_count: 3 } })
  })
  const error = await designedProbe(page, { enabled: true })
  expect(error).toBeNull()
  expect(legacyCalled).toBe(false)
  expect(keys).toHaveLength(1)
  expect(keys[0]).toMatch(/^[A-Za-z0-9._:-]{8,128}$/)
  expect(payload).toMatchObject({ contract_version: 1, mode: 'designed', source: 'excel', require_rsvp: true, templates: { normal: 'test-template' } })
  expect(payload.rows[0]).toMatchObject({ guest_count: 3, ticket_class: 'normal' })
  expect(payload.rows[0].metadata.custom_fields['رقم الجوال']).toBe('+967700000000')
  expect(payload.output_formats).toEqual([])
})

test('a lost response is retried with the same Idempotency-Key, a changed request gets a new one', async ({ page }) => {
  await page.goto('/auth/login')
  const result = await page.evaluate(async () => {
    const path = '/src/features/events/api/generationOperationsApi.ts'
    const { submitOperation } = await import(/* @vite-ignore */ path)
    const clientPath = '/src/services/http/client.ts'
    const { default: http } = await import(/* @vite-ignore */ clientPath)
    const seen: string[] = []
    let fail = true
    http.defaults.adapter = async (config: any) => {
      seen.push(config.headers['Idempotency-Key'] ?? config.headers.get?.('Idempotency-Key'))
      if (fail) { fail = false; throw new Error('network lost') }
      return { data: { id: 'op', status: 'queued' }, status: 202, statusText: 'Accepted', headers: {}, config }
    }
    const body = { contract_version: 1, event_id: 'e', mode: 'quick', source: 'count', count: { vip_count: 0, normal_count: 2, guest_name_prefix: 'ضيف' }, output_formats: [], require_rsvp: false }
    try { await submitOperation(body, 't') } catch { /* response lost */ }
    await submitOperation(body, 't')
    await submitOperation({ ...body, count: { ...body.count, normal_count: 3 } }, 't')
    return seen
  })
  expect(result[0]).toBe(result[1])
  expect(result[2]).not.toBe(result[0])
})

test('Excel count rejects fractions instead of silently truncating them', async ({ page }) => {
  await page.goto('/auth/login')
  const result = await page.evaluate(async () => {
    const path = '/src/features/events/utils/mappingUtils.ts'
    const { resolveGuestCount } = await import(/* @vite-ignore */ path)
    let rejected = false
    try { resolveGuestCount({ 'عدد الأشخاص': 2.5 }) } catch { rejected = true }
    return { rejected, valid: resolveGuestCount({ 'عدد الأشخاص': '٣' }) }
  })
  expect(result).toEqual({ rejected: true, valid: 3 })
})

test('expired aggregate download is refreshed before fetching without credentials', async ({ page }) => {
  const original = 'https://supdawaa.prideidea.com/storage/v1/object/sign/invitations/tenant/event/batches/batch/result.pdf?token=expired'
  const fresh = original.replace('expired', 'fresh')
  let fetched = false
  await page.route('**/api/v1/fast-invitations/refresh-download', async route => {
    expect(route.request().postDataJSON()).toEqual({ reference: original })
    await route.fulfill({ json: { download_url: fresh } })
  })
  await page.route(fresh, async route => {
    const headers = route.request().headers()
    expect(headers.authorization).toBeUndefined()
    expect(headers['x-tenant-id']).toBeUndefined()
    expect(headers.cookie).toBeUndefined()
    fetched = true
    await route.fulfill({ contentType: 'application/pdf', headers: { 'Access-Control-Allow-Origin': '*' }, body: '%PDF-1.4' })
  })
  await page.goto('/auth/login')
  const download = page.waitForEvent('download')
  await page.evaluate(async original => {
    const path = '/src/services/http/client.ts'
    const { downloadAuthenticatedFile, setAccessToken } = await import(/* @vite-ignore */ path)
    setAccessToken('private-test-token')
    await downloadAuthenticatedFile(original, 'invitations.pdf')
  }, original)
  expect((await download).suggestedFilename()).toBe('invitations.pdf')
  expect(fetched).toBe(true)
})
