import { test, expect } from '@playwright/test'

test('import checks required cell values rather than only column names', async ({ page }) => {
  await page.goto('/auth/login')
  const result = await page.evaluate(async () => {
    const harnessPath = '/e2e/generation-hook-harness.tsx'
    const { mountDesignProbe } = await import(/* @vite-ignore */ harnessPath)
    let ready = false
    let errors: string[] = []
    const noop = () => {}
    const state = new Proxy({ dynamicFields: [{data_key:'guest.name',label:'اسم الضيف',required:true}], designExcelRows:[] }, {
      get(target, key) {
        if (key === 'setDesignExcelReady') return (value: boolean) => { ready = value }
        if (key === 'setDesignMappingErrors') return (value: string[]) => { errors = value }
        if (String(key).startsWith('set')) return noop
        return Reflect.get(target, key)
      },
    })
    const { api, unmount } = await mountDesignProbe(state, {})
    await api.handleDesignExcelUpload(new File(['اسم الضيف,عدد الدعوات\nأحمد,1\n,2'], 'guests.csv', {type:'text/csv'}))
    const blank = { ready, errors: [...errors] }
    await api.handleDesignExcelUpload(new File(['اسم الضيف,عدد الدعوات\nأحمد,1\nسارة,2'], 'guests.csv', {type:'text/csv'}))
    const complete = { ready, errors: [...errors] }
    unmount()
    return { blank, complete }
  })
  expect(result.blank.ready).toBe(false)
  expect(result.blank.errors.join(' ')).toContain('خلايا فارغة')
  expect(result.complete.ready).toBe(true)
  expect(result.complete.errors).toEqual([])
})
