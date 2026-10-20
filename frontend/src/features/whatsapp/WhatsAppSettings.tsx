import { useEffect, useState } from 'react'
import { isAxiosError } from 'axios'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MessageCircle, RefreshCw, QrCode, Loader2 } from 'lucide-react'
import { useAuthStore } from '@features/auth/store/authStore'
import { getApiErrorMessage } from '@services/http/client'
import { whatsappAPI, stateLabel, type Connection } from './api'
import './whatsapp.css'

export function WhatsAppSettings() {
 const tenantId = useAuthStore(s => s.currentTenantId)
 const qc = useQueryClient()
 const [qr, setQr] = useState<string | null>(null)
 const [pairing, setPairing] = useState(false)
 const [message, setMessage] = useState('')
 const queryKey = ['whatsapp-connection', tenantId]
 const query = useQuery({ queryKey, queryFn: whatsappAPI.connection })
 const conn = query.data
 // The provider rotates QR codes. Fetch current status before fetching a code;
 // a successful handshake must clear the previous code, even before READY.
 const live = useQuery({
   queryKey: ['whatsapp-pairing', tenantId],
   enabled: pairing && !!conn?.configured && !!conn.feature_enabled && conn.linked,
   queryFn: async () => {
     const status = await whatsappAPI.refresh()
     let code = null
     if (status.status === 'qr_ready') {
       try { code = await whatsappAPI.qr() }
       catch (error) {
         // QR renewal can pause, or authentication can begin between the two
         // requests. A missing QR is temporary; keep checking at normal pace.
         if (!isAxiosError(error) || error.response?.status !== 409) throw error
       }
     }
     if (code && !code.qrCode.startsWith('data:image/png;base64,')) throw new Error('رمز ربط غير صالح')
     return { ...status, qr: code?.qrCode || null }
   },
   retry: false,
   gcTime: 0,
   refetchOnWindowFocus: 'always',
   refetchInterval: q => Math.min(5000 * 2 ** q.state.fetchFailureCount, 30000),
 })
 useEffect(() => {
   if (!pairing || !live.data || live.isError) return
   const status = live.data.status
   setQr(document.hidden ? null : live.data.qr)
   setMessage('')
   qc.setQueryData<Connection>(['whatsapp-connection', tenantId], previous => previous ? {
     ...previous, status, phone: live.data.phone, last_checked_at: new Date().toISOString(),
   } : previous)
   if (status === 'ready') {
     setPairing(false)
     setMessage('تم ربط الرقم بنجاح. يمكنك الآن تفعيل الإرسال.')
   } else if (['failed', 'disconnected'].includes(status)) {
     setPairing(false)
     setMessage('توقفت محاولة الربط. اضغط إعادة الاتصال للحصول على رمز جديد.')
   }
 }, [pairing, live.data, live.dataUpdatedAt, live.isError, qc, tenantId])
 useEffect(() => {
   if (pairing && live.isError) {
     setQr(null)
     setMessage('تعذر تحديث رمز الربط. جارٍ إعادة المحاولة؛ انتظر ظهور رمز جديد قبل المسح.')
   }
 }, [pairing, live.isError, live.errorUpdatedAt])
 useEffect(() => {
   if (!pairing) return
   const timeout = window.setTimeout(() => {
     setPairing(false)
     setQr(null)
     setMessage('انتهت مهلة عرض الرمز. اضغط عرض رمز الربط لبدء محاولة جديدة.')
   }, 180000)
   // Never keep a code from a suspended/background tab visible on return.
   const hideStaleCode = () => { if (document.hidden) setQr(null) }
   document.addEventListener('visibilitychange', hideStaleCode)
   return () => {
     window.clearTimeout(timeout)
     document.removeEventListener('visibilitychange', hideStaleCode)
   }
 }, [pairing])
 useEffect(() => {
   setPairing(false)
   setQr(null)
   setMessage('')
 }, [tenantId])
 useEffect(() => {
   if (conn && (!conn.configured || !conn.feature_enabled || !conn.linked)) {
     setPairing(false)
     setQr(null)
   }
 }, [conn?.configured, conn?.feature_enabled, conn?.linked])
 const action = useMutation({ mutationFn: async (kind: 'link' | 'refresh' | 'qr' | 'toggle') => {
   setMessage('')
   setQr(null)
   setPairing(false)
   // Discard a cached QR before a new pairing attempt.
   await qc.cancelQueries({ queryKey: ['whatsapp-pairing', tenantId] })
   qc.removeQueries({ queryKey: ['whatsapp-pairing', tenantId] })
   if (kind === 'link') await whatsappAPI.link()
   else if (kind === 'refresh') await whatsappAPI.refresh()
   else if (kind === 'toggle') await whatsappAPI.enable(!conn?.enabled)
 }, onSuccess: async (_, kind) => {
   await qc.invalidateQueries({ queryKey: ['whatsapp-connection', tenantId] })
   if (kind === 'link' || kind === 'qr') setPairing(true)
 }, onError: e => setMessage(getApiErrorMessage(e)) })
 const hideQr = () => { setPairing(false); setQr(null) }
 return <section className="settings-section wa-panel" dir="rtl">
  <header><MessageCircle size={24} /><div><span>قنوات الإرسال</span><h2>WhatsApp</h2><p>اربط رقم المؤسسة لإرسال رابط تأكيد الحضور أو الدعوة الفردية، وتابع التسليم لكل ضيف.</p></div></header>
  {query.isLoading ? <Loader2 className="spin" /> : query.isError ? <p role="alert">{getApiErrorMessage(query.error)} <button onClick={() => query.refetch()}>إعادة المحاولة</button></p> : <>
   <div className="wa-status"><strong>{stateLabel[conn?.status || 'not_connected'] || 'تعذر التحقق'}</strong><span dir="ltr">{conn?.phone || 'لم يتم ربط رقم'}</span><span>الإرسال: {conn?.enabled ? 'مفعّل' : 'معطّل'}</span></div>
   {!conn?.configured && <p className="wa-note">خدمة WhatsApp لم تُجهز على الخادم بعد. تظهر أدوات الربط عند إكمال إعداد الخدمة.</p>}
   {!conn?.feature_enabled && <p className="wa-note">الميزة غير مفعلة للمؤسسة. يمكن لمسؤول المنصة مراجعة ميزات الباقة.</p>}
   <div className="wa-actions">
    {conn?.configured && conn.feature_enabled && <button className="settings-btn settings-btn--primary" disabled={action.isPending || pairing} onClick={() => action.mutate('link')}><QrCode size={17} />{conn.linked ? 'إعادة الاتصال' : 'ربط رقم المؤسسة'}</button>}
    {conn?.linked && <button className="settings-btn" disabled={action.isPending || pairing} onClick={() => action.mutate('refresh')}><RefreshCw size={17} />تحديث الحالة</button>}
    {conn?.configured && conn.feature_enabled && conn.linked && !['ready', 'authenticating'].includes(conn.status) && !pairing && <button className="settings-btn" disabled={action.isPending} onClick={() => action.mutate('qr')}>عرض رمز الربط</button>}
    {conn?.linked && (conn.enabled || (conn.configured && conn.feature_enabled && conn.status === 'ready')) && <button className="settings-btn" disabled={action.isPending} onClick={() => action.mutate('toggle')}>{conn.enabled ? 'تعطيل الإرسال وإلغاء الطابور' : 'تفعيل الإرسال'}</button>}
   </div>
   {conn?.last_checked_at && <small>آخر تحقق: {new Date(conn.last_checked_at).toLocaleString('ar', { timeZone: 'Asia/Aden' })}</small>}
   {pairing && <div className="wa-qr">
    {qr ? <img src={qr} alt="رمز ربط رقم WhatsApp للمؤسسة" /> : <Loader2 className="spin" aria-label="جارٍ متابعة الربط" />}
    <p>{conn?.status === 'authenticating' ? 'تم مسح الرمز. انتظر اكتمال الربط على الهاتف.' : !qr ? 'جارٍ الحصول على رمز ربط جديد. سيظهر تلقائياً عند جاهزيته.' : 'من WhatsApp على هاتف المؤسسة: الأجهزة المرتبطة ← ربط جهاز. امسح الرمز الظاهر الآن؛ يتحدث الرمز وحالة الربط تلقائياً.'}</p>
    <button className="settings-btn" onClick={hideQr}>إخفاء الرمز</button>
   </div>}
  </>}
  {message && <p role={conn?.status === 'ready' ? 'status' : 'alert'} className={conn?.status === 'ready' ? 'wa-note' : 'wa-error'}>{message}</p>}
  <p className="wa-note">تعطيل الإرسال يلغي الرسائل التي لم تبدأ. الرسائل التي بدأت بالفعل تبقى في سجلها حتى تتضح النتيجة.</p>
 </section>
}
