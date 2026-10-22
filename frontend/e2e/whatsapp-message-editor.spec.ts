import {test,expect,type Page} from '@playwright/test'
import {tablePayload,historyPayload} from './invitation-table-mocks'
const permissions=['whatsapp.send','whatsapp.view','ui.invitations.action.send','ui.event.tab.settings']
const guest={id:'guest-one',guest_name:'سارة أحمد',guest_phone:'+967700000001',status:'accepted',rsvp_status:'accepted',metadata:{require_rsvp:true},ticket_class:'normal',plus_one_count:0,guest_count:1,checkin_count:0,token:'personal-link',created_at:'2026-10-12T15:00:00Z'}
const defaults={rsvp_text:'مرحباً {guest_name}، يرجى تأكيد حضورك في {event_name}.',ticket_text:'أهلاً {guest_name}، دعوتك إلى {event_name}.'}
const tinyPNG=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==','base64')
async function mount(page:Page,perms=permissions){await page.goto('/auth/login');await page.evaluate(async permissions=>{const path='/e2e/whatsapp-harness.tsx';const {mountWhatsApp}=await import(/* @vite-ignore */path);mountWhatsApp(permissions,false)},perms)}
async function mocks(page:Page){
 let config:any={...defaults,image_id:null,version:0,defaults,sample_values:{guest_name:'اسم الضيف',event_name:'حفل الاختبار',event_date:'2026/10/13، 15:00',event_location:'قاعة الاختبار'},sample_link:'https://example.com/i/رابط-الضيف'}
 const saved:any[]=[]
 await page.route('**/api/v1/**',route=>{
  const url=new URL(route.request().url()),path=url.pathname
  if(path.endsWith('/message/image'))return route.fulfill({json:{image_id:'image-one',size:1000}})
  if(path.includes('/message/images/'))return route.fulfill({body:tinyPNG,contentType:'image/png'})
  if(path.endsWith('/message/preview'))return route.fulfill({json:{version:config.version,image_id:config.image_id,too_long:0,samples:[{purpose:'ticket',guest_name:guest.guest_name,text:config.ticket_text.replace('{guest_name}',guest.guest_name).replace('{event_name}','حفل الاختبار')+'\n\nhttps://example.com/i/personal-link'}]}})
  if(path.endsWith('/message')){
   if(route.request().method()==='PUT'){const data=route.request().postDataJSON();saved.push(data);config={...config,...data,version:config.version+1}}
   return route.fulfill({json:config})
  }
  return route.fulfill({json:path.endsWith('/whatsapp/connection')?{configured:true,feature_enabled:true,linked:true,enabled:true,status:'ready',phone:'967700000000'}:path.endsWith('/invitations/table')?tablePayload(url,[guest]):path.endsWith('/whatsapp/deliveries/page')?historyPayload([],url):[]})
 })
 return {saved}
}

test('edit both messages add variables and image then preview saved message',async({page})=>{
 const state=await mocks(page);await mount(page)
 await page.getByRole('button',{name:'تخصيص الرسالة',exact:true}).click()
 const editor=page.getByRole('dialog',{name:'تخصيص رسالة WhatsApp'})
 await editor.getByLabel('نص الرسالة').fill('يسعدنا لقاؤك يا ')
 await editor.getByRole('button',{name:'+ اسم الضيف',exact:true}).click()
 await expect(editor.getByLabel('نص الرسالة')).toHaveValue('يسعدنا لقاؤك يا {guest_name}')
 await editor.getByRole('tab',{name:'الدعوة الجاهزة للدخول'}).click()
 await editor.getByLabel('نص الرسالة').fill('مرحباً {guest_name}، هذه دعوتك المميزة إلى {event_name}.')
 await editor.getByLabel('رفع صورة الرسالة').setInputFiles({name:'event.png',mimeType:'image/png',buffer:tinyPNG})
 await expect(editor.getByRole('img',{name:'صورة رسالة الدعوة'})).toBeVisible()
 await editor.getByRole('button',{name:'حفظ الرسالة',exact:true}).click()
 await expect(editor).not.toBeVisible()
 expect(state.saved[0].image_id).toBe('image-one');expect(state.saved[0].rsvp_text).toBe('يسعدنا لقاؤك يا {guest_name}')
 await page.getByRole('checkbox',{name:'تحديد سارة أحمد',exact:true}).check()
 await page.getByRole('button',{name:'إرسال المحدد (1)',exact:true}).click()
 const confirmation=page.getByRole('dialog',{name:'تأكيد الإرسال عبر WhatsApp'})
 await expect(confirmation.getByText('مرحباً سارة أحمد، هذه دعوتك المميزة إلى حفل الاختبار.',{exact:false})).toBeVisible()
 await expect(confirmation.getByRole('img',{name:'صورة رسالة الدعوة'})).toBeVisible()
 await expect(confirmation.getByRole('button',{name:'إرسال إلى 1 ضيف'})).toBeEnabled()
})

test('sender without event edit permission cannot customize shared message',async({page})=>{
 await mocks(page);await mount(page,permissions.filter(p=>p!=='ui.event.tab.settings'))
 await expect(page.getByRole('button',{name:'إرسال المحدد (0)'})).toBeVisible()
 await expect(page.getByRole('button',{name:'تخصيص الرسالة'})).toHaveCount(0)
})

test('preview failure prevents sending and can be reloaded',async({page})=>{
 await mocks(page);let unavailable=true
 await page.route('**/api/v1/whatsapp/events/*/message/preview',route=>route.fulfill(unavailable?{status:503,json:{detail:'تعذر تحميل المعاينة'}}:{json:{version:0,image_id:null,too_long:0,samples:[]}}))
 await mount(page)
 await page.getByRole('checkbox',{name:'تحديد سارة أحمد',exact:true}).check()
 await page.getByRole('button',{name:'إرسال المحدد (1)',exact:true}).click()
 await expect(page.getByRole('button',{name:'إرسال إلى 1 ضيف'})).toBeDisabled()
 await expect(page.getByRole('alert').filter({hasText:'تعذر تحميل المعاينة'})).toBeVisible()
 unavailable=false;await page.getByRole('button',{name:'إعادة تحميل المعاينة'}).click()
 await expect(page.getByRole('button',{name:'إرسال إلى 1 ضيف'})).toBeEnabled()
})

test('editor fits light and dark displays and removes image explicitly',async({page})=>{
 const state=await mocks(page);await mount(page)
 await page.getByRole('button',{name:'تخصيص الرسالة',exact:true}).click()
 const editor=page.getByRole('dialog',{name:'تخصيص رسالة WhatsApp'})
 await expect(editor.getByLabel('نص الرسالة')).toBeVisible()
 for(const theme of ['light','dark']){
  await page.evaluate(value=>document.documentElement.setAttribute('data-theme',value),theme)
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true)
  const bounds=await editor.boundingBox();expect(bounds!.width).toBeLessThanOrEqual(page.viewportSize()!.width)
  await page.screenshot({path:`/tmp/wa-message-editor-${theme}-${test.info().project.name}.png`,fullPage:true,animations:'disabled'})
 }
 await editor.getByLabel('رفع صورة الرسالة').setInputFiles({name:'x.png',mimeType:'image/png',buffer:tinyPNG})
 await expect(editor.getByRole('button',{name:'إزالة الصورة'})).toBeVisible()
 await editor.getByRole('button',{name:'إزالة الصورة'}).click()
 await editor.getByRole('button',{name:'حفظ الرسالة',exact:true}).click()
 expect(state.saved[0].image_id).toBeNull()
})

test('changed message requires fresh preview and a new request only after explicit rejection',async({page})=>{
 await mocks(page)
 let version=0
 const sends:any[]=[]
 await page.route('**/api/v1/whatsapp/events/*/message/preview',route=>route.fulfill({json:{version,image_id:null,too_long:0,samples:[]}}))
 await page.route('**/api/v1/whatsapp/deliveries',route=>{
  sends.push(route.request().postDataJSON())
  if(sends.length===1){version=1;return route.fulfill({status:409,json:{detail:{code:'WHATSAPP_MESSAGE_CHANGED',message:'تغيرت الرسالة بعد المعاينة'}}})}
  return route.fulfill({status:202,json:{queued:1,skipped:0,items:[]}})
 })
 await mount(page)
 await page.getByRole('checkbox',{name:'تحديد سارة أحمد',exact:true}).check()
 await page.getByRole('button',{name:'إرسال المحدد (1)',exact:true}).click()
 await page.getByRole('button',{name:'إرسال إلى 1 ضيف'}).click()
 await expect(page.getByRole('dialog',{name:'تأكيد الإرسال عبر WhatsApp'})).not.toBeVisible()
 await expect(page.getByText('تغيرت الرسالة بعد المعاينة',{exact:true})).toBeVisible()
 await page.getByRole('button',{name:'إرسال المحدد (1)',exact:true}).click()
 await page.getByRole('button',{name:'إرسال إلى 1 ضيف'}).click()
 await expect(page.getByText('أُضيفت 1 رسالة للطابور.',{exact:true})).toBeVisible()
 expect(sends[0].message_versions).toEqual({'event-one':0})
 expect(sends[1].message_versions).toEqual({'event-one':1})
 expect(sends[0].client_request_id).not.toBe(sends[1].client_request_id)
})
