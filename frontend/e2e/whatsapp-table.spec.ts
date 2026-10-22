import { tablePayload, historyPayload, messagePreviewPayload } from './invitation-table-mocks'
import { test, expect, type Page } from '@playwright/test'
const sender=['whatsapp.send','ui.invitations.action.send','whatsapp.view','whatsapp.manage']
const connection={configured:true,feature_enabled:true,linked:true,enabled:true,status:'ready',phone:'967700000000'}
const base={guest_phone:'+967700000001',status:'created',rsvp_status:'pending',metadata:{require_rsvp:true},ticket_class:'normal',plus_one_count:0,guest_count:1,checkin_count:0,token:'sample-token',created_at:'2026-10-12T15:00:00Z',updated_at:'2026-10-12T15:00:00Z'}
const guests=[
 {...base,id:'guest-one',guest_name:'سارة أحمد'},
 {...base,id:'guest-two',guest_name:'محمد علي',rsvp_status:'accepted',status:'accepted'},
 {...base,id:'guest-three',guest_name:'ريم خالد'},
 {...base,id:'guest-four',guest_name:'حسن عمر'},
 {...base,id:'guest-five',guest_name:'ليلى صالح'},
 {...base,id:'guest-six',guest_name:'ضيف بلا رقم',guest_phone:null},
 {...base,id:'guest-seven',guest_name:'علي حسن',rsvp_status:'accepted',status:'accepted'},
]
const record=(id:string,purpose:string,state:string)=>({id:`delivery-${id}`,invitation_id:id,purpose,state,recipient:'967700000001',guest_name:guests.find(i=>i.id===id)?.guest_name,error_code:null,created_at:'2026-10-12T15:00:00Z',updated_at:'2026-10-12T15:02:00Z',attempt_count:1})
const statuses=[record('guest-two','rsvp','sent'),record('guest-three','rsvp','read'),record('guest-four','rsvp','unknown'),record('guest-five','rsvp','failed'),record('guest-seven','ticket','delivered')]
async function mount(page:Page,permissions=sender,final=false){
 await page.goto('/auth/login')
 await page.evaluate(async({permissions,final})=>{
  const path='/e2e/whatsapp-harness.tsx'
  const {mountWhatsApp}=await import(/* @vite-ignore */ path)
  mountWhatsApp(permissions,false,final)
 },{permissions,final})
}
async function mocks(page:Page, rows=guests, summaries=statuses){
 await page.route('**/api/v1/**',route=>{
  const path=new URL(route.request().url()).pathname
  return route.fulfill({json:path.endsWith('/message/preview')?messagePreviewPayload(rows.filter(i=>route.request().postDataJSON().invitation_ids.includes(i.id))):path.endsWith('/whatsapp/connection')?connection:path.endsWith('/invitations/table')?tablePayload(new URL(route.request().url()),rows,summaries):path.endsWith('/whatsapp/deliveries/page')?historyPayload(summaries,new URL(route.request().url())):[]})
 })
}
const row=(page:Page,name:string)=>page.getByRole('row').filter({has:page.getByText(name,{exact:true})})

test('delivery states and message purposes appear in the main table',async({page})=>{
 await mocks(page);await mount(page)
 await expect(page.getByRole('columnheader',{name:'WhatsApp',exact:true})).toBeVisible()
 await expect(row(page,'سارة أحمد').getByText('لم تُرسل',{exact:true})).toBeVisible()
 await expect(row(page,'محمد علي').getByText('لم تُرسل',{exact:true})).toBeVisible()
 await expect(row(page,'محمد علي').getByText('طلب تأكيد الحضور: تم الإرسال')).toBeVisible()
 await expect(row(page,'ريم خالد').getByText('تمت القراءة',{exact:true})).toBeVisible()
 await expect(row(page,'حسن عمر').getByRole('checkbox')).toBeDisabled()
 await expect(row(page,'ضيف بلا رقم').getByRole('checkbox')).toBeDisabled()
 await row(page,'سارة أحمد').getByRole('checkbox').check()
 await expect(page.getByRole('button',{name:'إرسال المحدد (1)',exact:true})).toBeEnabled()
 await expect(page.getByRole('heading',{name:'تفاصيل رد الضيف (RSVP)',exact:true})).toHaveCount(0)
 await expect(page.locator('.wa-recipient-list')).toHaveCount(0)
})
test('filters compose with search and send only visible selected guests',async({page})=>{
 const requests:any[]=[]
 await mocks(page)
 await page.route('**/api/v1/whatsapp/deliveries',route=>{
  requests.push(route.request().postDataJSON());return route.fulfill({status:202,json:{queued:1,skipped:0,items:[]}})
 })
 await mount(page)
 await page.getByRole('combobox',{name:'حالة إرسال WhatsApp'}).selectOption('not_sent')
 await expect(row(page,'ريم خالد')).toHaveCount(0)
 await page.getByPlaceholder('بحث بالاسم أو الهاتف...').fill('محمد')
 await expect(row(page,'سارة أحمد')).toHaveCount(0)
 await page.getByRole('checkbox',{name:'تحديد الصفحة الحالية (حتى 100)',exact:true}).check()
 await page.getByRole('button',{name:'إرسال المحدد (1)',exact:true}).click()
 await expect(page.getByRole('dialog',{name:'تأكيد الإرسال عبر WhatsApp'})).toBeVisible()
 await expect(page.getByText('1 رابط دعوة',{exact:true})).toBeVisible()
 await page.getByRole('button',{name:'إرسال إلى 1 ضيف',exact:true}).click()
 await expect(page.getByText('أُضيفت 1 رسالة للطابور.',{exact:true})).toBeVisible()
 expect(requests[0].invitation_ids).toEqual(['guest-two'])
 expect(requests[0].allow_resend).toBe(false)
})
test('changing filters clears hidden selection and select-unsent respects filters',async({page})=>{
 await mocks(page);await mount(page)
 await row(page,'سارة أحمد').getByRole('checkbox').check()
 await page.getByRole('combobox',{name:'حالة إرسال WhatsApp'}).selectOption('read')
 await expect(page.getByRole('button',{name:'إرسال المحدد (0)',exact:true})).toBeDisabled()
 await page.getByRole('combobox',{name:'حالة إرسال WhatsApp'}).selectOption('not_sent')
 await page.getByRole('button',{name:'تحديد غير المرسلة',exact:true}).click()
 await expect(page.getByRole('button',{name:'إرسال المحدد (2)',exact:true})).toBeEnabled()
})
test('row history targets that guest and review requires evidence',async({page})=>{
 let historyId:string|null=null
 let reviewPayload:any
 await mocks(page)
 await page.route('**/api/v1/whatsapp/deliveries/page?*',route=>{
  historyId=new URL(route.request().url()).searchParams.get('invitation_id')
  return route.fulfill({json:historyPayload([{...record('guest-four','rsvp','unknown'),error_code:'send_result_unknown'}],new URL(route.request().url()))})
 })
 await page.route('**/api/v1/whatsapp/deliveries/delivery-guest-four/review',route=>{
  reviewPayload=route.request().postDataJSON();return route.fulfill({json:{reviewed:true}})
 })
 await mount(page)
 await row(page,'حسن عمر').getByRole('button',{name:'سجل WhatsApp للضيف حسن عمر',exact:true}).click()
 await expect(page.getByRole('dialog',{name:'سجل الإرسال — حسن عمر'})).toBeVisible()
 expect(historyId).toBe('guest-four')
 await page.getByRole('button',{name:'مراجعة النتيجة',exact:true}).click()
 await expect(page.getByRole('button',{name:'حفظ المراجعة',exact:true})).toBeDisabled()
 await page.getByRole('combobox',{name:'نتيجة مراجعة الإرسال'}).selectOption('not_sent')
 await page.getByRole('textbox',{name:'دليل مراجعة الإرسال'}).fill('تم التحقق من هاتف المؤسسة ولم تظهر رسالة لهذا الضيف.')
 await page.getByRole('button',{name:'حفظ المراجعة',exact:true}).click()
 await expect(page.getByRole('button',{name:'حفظ المراجعة',exact:true})).toHaveCount(0)
 expect(reviewPayload.outcome).toBe('not_sent')
})
test('final invitations share selection with independent ticket delivery status',async({page})=>{
 await mocks(page);await mount(page,sender,true)
 await expect(row(page,'محمد علي').getByText('لم تُرسل',{exact:true})).toBeVisible()
 await expect(row(page,'علي حسن').getByText('تم التسليم',{exact:true})).toBeVisible()
 await page.getByRole('combobox',{name:'حالة إرسال WhatsApp'}).selectOption('not_sent')
 await expect(row(page,'علي حسن')).toHaveCount(0)
 await page.getByRole('button',{name:'تحديد غير المرسلة',exact:true}).click()
 await expect(page.getByRole('button',{name:'إرسال المحدد (1)',exact:true})).toBeEnabled()
})
test('unavailable delivery state is never marked as unsent',async({page})=>{
 await mocks(page)
 await page.route('**/api/v1/invitations/table?*',route=>route.fulfill({status:503,json:{detail:'unavailable'}}))
 await mount(page)
 await expect(page.getByRole('alert').filter({hasText:'تعذر تحديث حالات الإرسال'})).toBeVisible()
 await expect(page.getByRole('button',{name:'إرسال المحدد (0)',exact:true})).toBeDisabled()
 await expect(page.getByRole('button',{name:'تحديد غير المرسلة',exact:true})).toBeDisabled()
})
test('page selection never includes guests on another page',async({page})=>{
 const rows=Array.from({length:101},(_,i)=>({...base,id:`many-${i}`,guest_name:`ضيف ${i+1}`}))
 await mocks(page,rows,[])
 await mount(page)
 await page.getByRole('combobox',{name:'صفحات الدعوات: صفوف الصفحة'}).selectOption('100')
 await page.getByRole('checkbox',{name:'تحديد الصفحة الحالية (حتى 100)',exact:true}).check()
 await expect(page.getByRole('button',{name:'إرسال المحدد (100)',exact:true})).toBeEnabled()
 await expect(row(page,'ضيف 101')).toHaveCount(0)
 await page.getByRole('button',{name:'التالي',exact:true}).click()
 await expect(row(page,'ضيف 101')).toBeVisible()
 await expect(page.getByRole('button',{name:'إرسال المحدد (0)',exact:true})).toBeDisabled()
})

test('light and dark controls stay within viewport',async({page})=>{
 await mocks(page);await mount(page)
 for(const theme of ['light','dark']){
  await page.evaluate(theme=>document.documentElement.setAttribute('data-theme',theme),theme)
  await expect(row(page,'سارة أحمد').getByText('لم تُرسل',{exact:true})).toBeVisible()
  expect(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth)).toBe(false)
  await page.screenshot({path:`/tmp/whatsapp-table-${theme}-${test.info().project.name}.png`,fullPage:true,animations:'disabled'})
 }
})


test('queued delivery updates in the main table without reopening a panel',async({page})=>{
 let state='queued'
 await mocks(page)
 await page.route('**/api/v1/invitations/table?*',route=>route.fulfill({json:tablePayload(new URL(route.request().url()),guests,[record('guest-one','rsvp',state)])}))
 await mount(page)
 await expect(row(page,'سارة أحمد').getByText('بانتظار التنفيذ',{exact:true})).toBeVisible()
 await expect(row(page,'سارة أحمد').getByRole('checkbox')).toBeDisabled()
 state='read'
 await expect(row(page,'سارة أحمد').getByText('تمت القراءة',{exact:true})).toBeVisible({timeout:22000})
 await expect(row(page,'سارة أحمد').getByRole('checkbox')).toBeEnabled()
})

test('three thousand invitations stay paged and searchable across the event',async({page})=>{
 const rows=Array.from({length:3000},(_,i)=>({...base,id:`scale-${i}`,guest_name:`ضيف رقم ${i+1}`}))
 await mocks(page,rows,[]);await mount(page)
 await expect(page.locator('.rsvp-table tbody tr')).toHaveCount(50)
 await expect(page.getByRole('navigation',{name:'صفحات الدعوات'})).toContainText(/3,000|٣٬٠٠٠/)
 await page.getByRole('spinbutton',{name:'صفحات الدعوات: الانتقال إلى صفحة'}).fill('60')
 await page.getByRole('button',{name:'انتقال',exact:true}).click()
 await expect(row(page,'ضيف رقم 3000')).toBeVisible()
 await page.getByPlaceholder('بحث بالاسم أو الهاتف...').fill('ضيف رقم 2999')
 await expect(page.locator('.rsvp-table tbody tr')).toHaveCount(1)
 await expect(row(page,'ضيف رقم 2999')).toBeVisible()
 await expect(page.getByRole('navigation',{name:'صفحات الدعوات'})).toContainText(/من [1١] نتيجة/)
})

test('history pages and filters work across thousands of attempts',async({page})=>{
 const records=Array.from({length:3000},(_,i)=>({...record('guest-one',i%2?'rsvp':'ticket',i%3?'sent':'failed'),id:`scale-delivery-${i}`,guest_name:`محاولة ${i+1}`}))
 await mocks(page)
 await page.route('**/api/v1/whatsapp/deliveries/page?*',route=>route.fulfill({json:historyPayload(records,new URL(route.request().url()))}))
 await mount(page)
 await page.getByRole('button',{name:'سجل الإرسال',exact:true}).click()
 const dialog=page.getByRole('dialog',{name:'سجل الإرسال',exact:true})
 await expect(dialog.locator('tbody tr')).toHaveCount(50)
 await dialog.getByRole('spinbutton',{name:'صفحات سجل الإرسال: الانتقال إلى صفحة'}).fill('60')
 await dialog.getByRole('button',{name:'انتقال',exact:true}).click()
 await expect(dialog.getByRole('cell',{name:/^محاولة 3000 /})).toBeVisible()
 await dialog.getByRole('textbox',{name:'البحث في سجل الإرسال'}).fill('محاولة 2999')
 await expect(dialog.locator('tbody tr')).toHaveCount(1)
 await expect(dialog.getByRole('cell',{name:/^محاولة 2999 /})).toBeVisible()
 await dialog.getByRole('combobox',{name:'حالة الرسالة في السجل'}).selectOption('failed')
 await expect(dialog.getByText('لا توجد محاولات إرسال في هذه الصفحة.')).toBeVisible()
})

test('export downloads all filtered results without a page limit',async({page})=>{
 let exportUrl:URL|undefined
 await mocks(page)
 await page.route('**/api/v1/invitations/table/export?*',route=>{
  exportUrl=new URL(route.request().url())
  return route.fulfill({body:'\ufeffالاسم,الهاتف\nضيف,967700000001',headers:{'content-type':'text/csv;charset=utf-8','content-disposition':'attachment; filename="invitations.csv"'}})
 })
 await mount(page,[...sender,'ui.rsvp.action.export'])
 await page.getByRole('combobox',{name:'حالة إرسال WhatsApp'}).selectOption('not_sent')
 await expect(page.getByRole('button',{name:'تصدير النتائج',exact:true})).toBeEnabled()
 const download=page.waitForEvent('download')
 await page.getByRole('button',{name:'تصدير النتائج',exact:true}).click()
 expect((await download).suggestedFilename()).toBe('invitations.csv')
 expect(exportUrl?.searchParams.get('whatsapp_state')).toBe('not_sent')
 expect(exportUrl?.searchParams.has('limit')).toBe(false)
 expect(exportUrl?.searchParams.has('offset')).toBe(false)
})
