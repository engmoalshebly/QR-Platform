import { test, expect } from '@playwright/test'

test('RSVP accepts built-in phone/email without custom field definitions and rejects missing contact', async ({ page }) => {
  await page.goto('/auth/login')
  const results = await page.evaluate(async () => {
    const hookPath = '/src/features/events/components/invitations/hooks/useQuickMode.ts'
    const reactPath = '/node_modules/.vite/deps/react.js'
    const domPath = '/node_modules/.vite/deps/react-dom_client.js'
    const { useQuickMode } = await import(/* @vite-ignore */ hookPath)
    const reactModule = await import(/* @vite-ignore */ reactPath)
    const React = reactModule.default || reactModule
    const domModule = await import(/* @vite-ignore */ domPath)
    const { createRoot } = domModule.default || domModule
    const output: any[] = []
    for (const fields of [{ 'رقم الجوال': '967700000000' }, { 'البريد الإلكتروني': 'guest@example.com' }, {}]) {
      let error: string | null = null
      let payload: any = null
      const state = new Proxy({
        generationSource: 'quick', quickInputMode: 'names', requireRsvp: true,
        quickDynamicFields: [], layout: {},
        quickManualGuests: [{ guest_name: 'ضيف', invitation_count: 1, ticket_class: 'vip', custom_fields: fields }],
      }, { get(target, key) {
        if (key === 'setLocalError') return (value: string | null) => { error = value }
        if (key === 'generate') return (value: any) => { payload = value }
        if (String(key).startsWith('set')) return () => {}
        return Reflect.get(target, key)
      } })
      const root = createRoot(document.createElement('div'))
      let api: any
      await new Promise<void>(resolve => {
        function Probe() { api = useQuickMode(state, { id: 'demo' }); React.useEffect(resolve, []); return null }
        root.render(React.createElement(Probe))
      })
      api.handleGenerate()
      output.push({ error, payload })
      root.unmount()
    }
    return output
  })
  for (const result of results.slice(0, 2)) {
    expect(result.error).toBeNull()
    expect(result.payload.invitations[0].metadata.require_rsvp).toBe(true)
  }
  expect(results[2].payload).toBeNull()
  expect(results[2].error).toContain('يفتقرون لبيانات الاتصال')
})
