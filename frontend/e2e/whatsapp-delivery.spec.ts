import { tablePayload, historyPayload, messagePreviewPayload } from './invitation-table-mocks'
import { test, expect, Page } from '@playwright/test'

async function mount(page: Page, permissions: string[], settings = false) {
 await page.goto('/auth/login')
 await page.evaluate(async ({permissions,settings}) => {
  const path='/e2e/whatsapp-harness.tsx'
  const {mountWhatsApp}=await import(/* @vite-ignore */ path)
  mountWhatsApp(permissions,settings)
 },{permissions,settings})
}

const invitation={id:'inv-one',guest_name:'ضيف الاختبار',guest_phone:'+967700000001',status:'created',rsvp_status:'pending',metadata:{require_rsvp:true},ticket_class:'normal',plus_one_count:0,guest_count:1,checkin_count:0,token:'test-token',created_at:'2026-10-12T15:00:00Z',updated_at:'2026-10-12T15:00:00Z'}
const connection={configured:true,feature_enabled:true,linked:true,enabled:true,status:'ready',phone:'967775451608'}
test.beforeEach(async ({page})=>{
 await page.route('**/api/v1/**',async route=>{
  const path=new URL(route.request().url()).pathname
  await route.fulfill({json:path.endsWith('/message/preview')?messagePreviewPayload([invitation]):path.endsWith('/whatsapp/connection')?connection:path.endsWith('/invitations/table')?tablePayload(new URL(route.request().url()),[invitation]):path.endsWith('/whatsapp/deliveries/page')?historyPayload([],new URL(route.request().url())):[]})
 })
})
test('retry preserves request identity after an unavailable response',async({page})=>{
 const requests:any[]=[]
 await page.route('**/api/v1/whatsapp/deliveries',async route=>{
  requests.push(route.request().postDataJSON())
  await route.fulfill(requests.length===1?{status:503,json:{detail:'تعذر الاتصال؛ أعد المحاولة'}}:{status:202,json:{queued:1,skipped:0,items:[]}})
 })
 await mount(page,['whatsapp.send','ui.invitations.action.send'])
 await page.getByRole('checkbox',{name:'تحديد ضيف الاختبار',exact:true}).check()
 await page.getByRole('button',{name:'إرسال المحدد (1)',exact:true}).click()
 await expect(page.getByText('معاينة الرسالة')).toBeVisible()
 await page.getByRole('button',{name:'إرسال إلى 1 ضيف'}).click()
 await expect(page.getByText('تعذر الاتصال؛ أعد المحاولة')).toBeVisible()
 await page.getByRole('button',{name:'إرسال إلى 1 ضيف'}).click()
 await expect(page.getByText(/أُضيفت 1 رسالة للطابور/)).toBeVisible()
 expect(requests).toHaveLength(2)
 expect(requests[0].client_request_id).toBe(requests[1].client_request_id)
})
test('viewer cannot send',async({page})=>{
 await mount(page,['whatsapp.view'])
 await page.getByRole('button',{name:'سجل الإرسال',exact:true}).click()
 await expect(page.getByRole('dialog',{name:'سجل الإرسال',exact:true})).toBeVisible()
 await expect(page.getByRole('checkbox')).toHaveCount(0)
 await expect(page.getByRole('button',{name:/إرسال إلى/})).toHaveCount(0)
})
test('unconfigured transport shows setup guidance',async({page})=>{
 await page.route('**/api/v1/whatsapp/connection',route=>route.fulfill({json:{...connection,configured:false,linked:false,enabled:false,status:'not_connected'}}))
 await mount(page,['whatsapp.manage'],true)
 await expect(page.getByText('خدمة WhatsApp لم تُجهز على الخادم بعد.',{exact:false})).toBeVisible()
 await expect(page.getByRole('button',{name:'ربط رقم المؤسسة'})).toHaveCount(0)
})

test('feature disabled hides delivery controls',async({page})=>{
 await page.route('**/api/v1/whatsapp/connection',route=>route.fulfill({json:{...connection,feature_enabled:false}}))
 await mount(page,['whatsapp.send','ui.invitations.action.send'])
 await expect(page.getByRole('button',{name:/إرسال المحدد/})).toHaveCount(0)
 await expect(page.getByRole('columnheader',{name:'WhatsApp',exact:true})).toHaveCount(0)
})

const qrFirst = 'data:image/png;base64,Zmlyc3Q='
const qrSecond = 'data:image/png;base64,c2Vjb25k'

test('pairing refreshes rotated QR and clears it during authentication', async ({page}) => {
 // Three polling phases plus the final no-poll observation can exceed 30s on CI.
 test.setTimeout(60000)
 let phase: 'qr_ready' | 'authenticating' | 'ready' = 'qr_ready'
 let qrRequests = 0
 await page.route('**/api/v1/whatsapp/connection', route => route.fulfill({json:{...connection,enabled:false,status:phase,phone:null}}))
 await page.route('**/api/v1/whatsapp/connection/refresh', route => route.fulfill({json:{status:phase,phone:phase==='ready'?'967700000000':null}}))
 await page.route('**/api/v1/whatsapp/connection/qr', route => route.fulfill({json:{qrCode:++qrRequests===1?qrFirst:qrSecond,status:'qr_ready'}}))
 await mount(page,['whatsapp.manage'],true)
 await page.getByRole('button',{name:'عرض رمز الربط'}).click()
 const image=page.getByRole('img',{name:'رمز ربط رقم WhatsApp للمؤسسة'})
 await expect(image).toHaveAttribute('src',qrFirst)
 await expect(image).toHaveAttribute('src',qrSecond,{timeout:10000})
 phase='authenticating'
 await expect(image).toHaveCount(0,{timeout:10000})
 await expect(page.getByText('تم مسح الرمز.',{exact:false})).toBeVisible()
 phase='ready'
 await expect(page.getByText('تم ربط الرقم بنجاح.',{exact:false})).toBeVisible({timeout:10000})
 await expect(page.getByRole('button',{name:'تفعيل الإرسال',exact:true})).toBeVisible()
 const count=qrRequests
 await page.waitForTimeout(5500)
 expect(qrRequests).toBe(count)
})

test('pairing discards a code on network failure and recovers with a fresh code',async({page})=>{
 let fail=false
 let code=qrFirst
 await page.route('**/api/v1/whatsapp/connection', route => route.fulfill({json:{...connection,enabled:false,status:'qr_ready',phone:null}}))
 await page.route('**/api/v1/whatsapp/connection/refresh', route => route.fulfill(fail?{status:503,json:{detail:'unavailable'}}:{json:{status:'qr_ready',phone:null}}))
 await page.route('**/api/v1/whatsapp/connection/qr', route => route.fulfill({json:{qrCode:code}}))
 await mount(page,['whatsapp.manage'],true)
 await page.getByRole('button',{name:'عرض رمز الربط'}).click()
 const image=page.getByRole('img',{name:'رمز ربط رقم WhatsApp للمؤسسة'})
 await expect(image).toHaveAttribute('src',qrFirst)
 fail=true
 await expect(page.getByText('تعذر تحديث رمز الربط.',{exact:false})).toBeVisible({timeout:10000})
 await expect(image).toHaveCount(0)
 code=qrSecond
 fail=false
 await expect(image).toHaveAttribute('src',qrSecond,{timeout:15000})
 await expect(page.getByText('تعذر تحديث رمز الربط.',{exact:false})).toHaveCount(0)
 await page.getByRole('button',{name:'إخفاء الرمز'}).click()
 await expect(image).toHaveCount(0)
})

test('hidden QR stops polling and a new attempt waits for a fresh response',async({page})=>{
 let code=qrFirst
 let refreshRequests=0
 let respond: (() => void) | undefined
 await page.route('**/api/v1/whatsapp/connection', route => route.fulfill({json:{...connection,enabled:false,status:'qr_ready',phone:null}}))
 await page.route('**/api/v1/whatsapp/connection/refresh', async route => {
  ++refreshRequests
  if(refreshRequests===2) await new Promise<void>(resolve=>{respond=resolve})
  await route.fulfill({json:{status:'qr_ready',phone:null}})
 })
 await page.route('**/api/v1/whatsapp/connection/qr', route => route.fulfill({json:{qrCode:code}}))
 await mount(page,['whatsapp.manage'],true)
 await page.getByRole('button',{name:'عرض رمز الربط'}).click()
 const image=page.getByRole('img',{name:'رمز ربط رقم WhatsApp للمؤسسة'})
 await expect(image).toHaveAttribute('src',qrFirst)
 await page.getByRole('button',{name:'إخفاء الرمز'}).click()
 await page.waitForTimeout(5500)
 expect(refreshRequests).toBe(1)
 code=qrSecond
 await page.getByRole('button',{name:'عرض رمز الربط'}).click()
 await expect.poll(()=>refreshRequests).toBe(2)
 await expect(image).toHaveCount(0)
 respond!()
 await expect(image).toHaveAttribute('src',qrSecond)
})

test('a late response cannot reveal QR in a hidden tab',async({page})=>{
 let respond: (()=>void) | undefined
 await page.route('**/api/v1/whatsapp/connection',route=>route.fulfill({json:{...connection,enabled:false,status:'qr_ready',phone:null}}))
 await page.route('**/api/v1/whatsapp/connection/refresh',route=>route.fulfill({json:{status:'qr_ready',phone:null}}))
 await page.route('**/api/v1/whatsapp/connection/qr',async route=>{
  await new Promise<void>(resolve=>{respond=resolve})
  await route.fulfill({json:{qrCode:qrFirst}})
 })
 await mount(page,['whatsapp.manage'],true)
 await page.getByRole('button',{name:'عرض رمز الربط'}).click()
 await expect.poll(()=>!!respond).toBe(true)
 await page.evaluate(()=>{
  Object.defineProperty(document,'hidden',{configurable:true,value:true})
  document.dispatchEvent(new Event('visibilitychange'))
 })
 const finished=page.waitForResponse('**/api/v1/whatsapp/connection/qr')
 respond!()
 await finished
 await page.waitForTimeout(250)
 await expect(page.getByRole('img',{name:'رمز ربط رقم WhatsApp للمؤسسة'})).toHaveCount(0)
})

test('provider QR expiry clears the image and waits for renewal',async({page})=>{
 let expired=false
 let renewed=false
 let reads=0
 await page.route('**/api/v1/whatsapp/connection',route=>route.fulfill({json:{...connection,enabled:false,status:'qr_ready',phone:null}}))
 await page.route('**/api/v1/whatsapp/connection/refresh',route=>route.fulfill({json:{status:'qr_ready',phone:null}}))
 await page.route('**/api/v1/whatsapp/connection/qr',route=>{
  ++reads
  return route.fulfill(expired?{status:409,json:{detail:'QR unavailable'}}:{json:{qrCode:renewed?qrSecond:qrFirst}})
 })
 await mount(page,['whatsapp.manage'],true)
 await page.getByRole('button',{name:'عرض رمز الربط'}).click()
 const image=page.getByRole('img',{name:'رمز ربط رقم WhatsApp للمؤسسة'})
 await expect(image).toHaveAttribute('src',qrFirst)
 expired=true
 await expect(image).toHaveCount(0,{timeout:10000})
 await expect(page.getByText('جارٍ الحصول على رمز ربط جديد.',{exact:false})).toBeVisible()
 expect(reads).toBeGreaterThan(1)
 expired=false
 renewed=true
 await expect(image).toHaveAttribute('src',qrSecond,{timeout:10000})
})
