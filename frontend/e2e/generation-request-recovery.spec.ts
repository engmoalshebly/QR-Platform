import { test, expect } from '@playwright/test'

test('request identity survives reload without retaining guest data and isolates accounts', async ({ page }) => {
  await page.goto('/auth/login')
  const getKey = () => page.evaluate(async () => {
    const { useAuthStore } = await import('/src/features/auth/store/authStore.ts')
    useAuthStore.setState({ user: { id: 'owner-one' } as any })
    const { generationRequestKey } = await import('/src/features/events/api/generationRequestKey.ts')
    return (await generationRequestKey('tenant-one', { guest_name: 'private-guest', phone: '+967700000000' })).key
  })
  const first = await getKey()
  await page.reload()
  expect(await getKey()).toBe(first)
  const result = await page.evaluate(async () => {
    const { generationRequestKey } = await import('/src/features/events/api/generationRequestKey.ts')
    const { useAuthStore } = await import('/src/features/auth/store/authStore.ts')
    useAuthStore.setState({ user: { id: 'owner-two' } as any })
    const next = await generationRequestKey('tenant-one', { guest_name: 'private-guest', phone: '+967700000000' })
    const retained = Object.keys(sessionStorage).filter(k => k.startsWith('generation-request:')).map(k => k + sessionStorage.getItem(k)).join('')
    return { key: next.key, retained }
  })
  expect(result.key).not.toBe(first)
  expect(result.retained).not.toContain('private-guest')
  expect(result.retained).not.toContain('967700000000')
})

test('artifact list loads remaining pages instead of hiding files', async ({ page }) => {
  const seen: string[] = []
  await page.route('**/api/v1/generation-operations/op-files/artifacts*', route => {
    const next = new URL(route.request().url()).searchParams.get('before')
    seen.push(next ?? 'first')
    return route.fulfill({ json: { items: [{ id: next ? 'file-last' : 'file-first', kind:'pdf', part_index:next ? 100 : 0, byte_size:1024, cards_count:10 }], next_cursor: next ? null : 'cursor-next' } })
  })
  await page.goto('/auth/login')
  await page.evaluate(async () => {
    const { mountFilesProbe } = await import('/e2e/generation-hook-harness.tsx')
    await mountFilesProbe('op-files')
  })
  await expect(page.locator('#files-probe')).toContainText('جزء 1')
  await page.getByRole('button', { name:'عرض المزيد من الملفات' }).click()
  await expect(page.locator('#files-probe')).toContainText('جزء 101')
  expect(seen).toEqual(['first', 'cursor-next'])
  await expect(page.getByRole('button', { name:'عرض المزيد من الملفات' })).toHaveCount(0)
})

test('designed mixed import requires both class templates and retains both classes', async ({ page }) => {
  await page.goto('/auth/login')
  await page.evaluate(async () => {
    const { mountMixedImportProbe } = await import('/e2e/generation-hook-harness.tsx')
    await mountMixedImportProbe()
  })
  const button = page.getByRole('button', { name:'إنشاء الدعوات (2 بطاقة)' })
  await expect(button).toBeDisabled()
  await page.getByLabel(/قالب فئة VIP/).selectOption('vip-template')
  await expect(button).toBeDisabled()
  await page.getByLabel(/قالب فئة العادي/).selectOption('normal-template')
  await button.click()
  expect(await page.evaluate(() => (window as any).__mixedGeneration)).toMatchObject({ mode:'designed', templates:{ vip:'vip-template', normal:'normal-template' }, formats:['pdf'] })
})

test('server draft restores rows and saves edits made during an in-flight save', async ({ page }) => {
  const saves: any[] = []
  await page.route('**/api/v1/generation-drafts/test-event/quick', async route => {
    if (route.request().method() === 'GET') return route.fulfill({ json:{ rows:[{ guest_name:'restored', custom_fields:{} }], revision:1 } })
    saves.push(route.request().postDataJSON())
    await new Promise(resolve => setTimeout(resolve, 500))
    return route.fulfill({ json:{ revision:saves.length + 1 } })
  })
  await page.goto('/auth/login')
  await page.evaluate(async () => {
    const { mountDraftProbe } = await import('/e2e/generation-hook-harness.tsx')
    await mountDraftProbe()
  })
  await expect(page.locator('#draft-probe')).toHaveText('restored')
  await page.evaluate(() => (window as any).__draftProbe.setRows([{ guest_name:'first-edit', custom_fields:{} }]))
  await expect.poll(() => saves.length).toBe(1)
  await page.evaluate(() => (window as any).__draftProbe.setRows([{ guest_name:'latest-edit', custom_fields:{} }]))
  await expect.poll(() => saves.length).toBe(2)
  expect(saves[1]).toMatchObject({ revision:2, rows:[{ guest_name:'latest-edit' }] })
})

test('legacy guest draft is removed only after the user requests a successful server transfer', async ({ page }) => {
  let fail = true
  await page.route('**/api/v1/generation-drafts/test-event/quick', route => {
    if (route.request().method() === 'GET') return route.fulfill({ json:{ rows:[], revision:0 } })
    return fail ? route.fulfill({ status:503, json:{ detail:'حفظ غير متاح' } }) : route.fulfill({ json:{ revision:1 } })
  })
  await page.goto('/auth/login')
  await page.evaluate(async () => {
    localStorage.setItem('event-invitations-quick-manual:test-event', JSON.stringify([{ guest_name:'legacy', custom_fields:{} }]))
    const { mountDraftProbe } = await import('/e2e/generation-hook-harness.tsx')
    await mountDraftProbe()
  })
  await expect.poll(() => page.evaluate(() => (window as any).__draftProbe?.ready)).toBe(true)
  await page.evaluate(() => (window as any).__draftProbe.restoreLegacy())
  expect(await page.evaluate(() => localStorage.getItem('event-invitations-quick-manual:test-event'))).toContain('legacy')
  fail = false
  await page.evaluate(() => (window as any).__draftProbe.restoreLegacy())
  await expect(page.locator('#draft-probe')).toContainText('legacy')
  expect(await page.evaluate(() => localStorage.getItem('event-invitations-quick-manual:test-event'))).toBeNull()
})

test('server import resumes its file identity and requires review again after reload', async ({ page }) => {
  await page.route('**/api/v1/auth/refresh', route => route.fulfill({ json:{ access_token:'test-access' } }))
  await page.route('**/api/v1/generation-imports/upload-one', route => route.fulfill({ json:{ id:'upload-one', event_id:'test-event', filename:'guests.csv', sheets:[{ name:'CSV' }], sheet:'CSV', delimiter:',', column_mapping:{ guest_name:'Name' }, require_rsvp:false, revision:2, summary:{ total:2,valid:2,selected:2 }, operation_id:null } }))
  const mount = () => page.evaluate(async () => {
    const { useAuthStore } = await import('/src/features/auth/store/authStore.ts')
    useAuthStore.setState({ user:{ id:'owner-one' } as any, currentTenantId:'tenant-one' })
    sessionStorage.setItem('generation-import:owner-one:tenant-one:test-event:designed', 'upload-one')
    const { mountImportProbe } = await import('/e2e/generation-hook-harness.tsx')
    await mountImportProbe()
  })
  await page.goto('/auth/login')
  await mount()
  await expect(page.locator('#import-probe')).toHaveText('guests.csv')
  await page.reload()
  await mount()
  await expect(page.locator('#import-probe')).toHaveText('guests.csv')
  expect(await page.evaluate(() => ({ revision:(window as any).__importProbe.revision, selectionReady:(window as any).__importProbe.selectionReady }))).toEqual({ revision:2, selectionReady:false })
})


test('JSONB key reordering preserves a pending request while guest order changes its identity', async ({ page }) => {
  await page.goto('/auth/login')
  const keys = await page.evaluate(async () => {
    const { useAuthStore } = await import('/src/features/auth/store/authStore.ts')
    useAuthStore.setState({ user:{ id:'owner-one' } as any })
    const { generationRequestKey } = await import('/src/features/events/api/generationRequestKey.ts')
    const before = { rows:[{ guest_name:'one', custom_fields:{ company:'A', phone:'123' } },{ guest_name:'two' }] }
    const restored = { rows:[{ custom_fields:{ phone:'123', company:'A' }, guest_name:'one' },{ guest_name:'two' }] }
    return [(await generationRequestKey('tenant-one', before)).key,
      (await generationRequestKey('tenant-one', restored)).key,
      (await generationRequestKey('tenant-one', { rows:[...restored.rows].reverse() })).key]
  })
  expect(keys[1]).toBe(keys[0])
  expect(keys[2]).not.toBe(keys[0])
})
