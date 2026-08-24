import { FormEvent, useEffect, useMemo, useState } from 'react'
import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { FieldShift, LoginResponse, TenantInfo } from './domain'
import { fieldApi, ApiError } from './lib/api'
import { defaultDeviceName, getFieldDeviceId } from './lib/device'
import { authSession } from './lib/session'
import { offlineStore } from './lib/offlineStore'
import { ScannerConsole } from './components/ScannerConsole'

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: true } },
})

const dateFormatter = new Intl.DateTimeFormat('ar-SA', { weekday: 'long', day: 'numeric', month: 'long' })
const timeFormatter = new Intl.DateTimeFormat('ar-SA', { hour: '2-digit', minute: '2-digit' })

function appError(error: unknown): string {
  return error instanceof ApiError || error instanceof Error ? error.message : 'حدث خطأ غير متوقع.'
}

function isoDate(date: Date) { return date.toISOString().slice(0, 10) }

function moveDate(value: string, days: number) {
  const date = new Date(`${value}T12:00:00`)
  date.setDate(date.getDate() + days)
  return isoDate(date)
}

function installServiceWorker() {
  if ('serviceWorker' in navigator) {
    void navigator.serviceWorker.register(`${import.meta.env.BASE_URL}service-worker.js`, {
      scope: import.meta.env.BASE_URL,
      updateViaCache: 'none',
    }).catch(() => undefined)
  }
}

function LoginScreen({ onLoggedIn }: { onLoggedIn: () => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [response, setResponse] = useState<LoginResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const login = useMutation({ mutationFn: ({ tenantId }: { tenantId?: string }) => fieldApi.login(email.trim(), password, tenantId) })

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    try {
      const result = await login.mutateAsync({})
      const selectable = (result.tenants || []).filter((tenant) => tenant.workspace_type === 'organizer' && tenant.membership_status === 'active')
      if (result.requires_tenant_selection || selectable.length !== 1) {
        setResponse(result)
        if (!selectable.length) setError('لا توجد مساحة فريق تشغيل نشطة مرتبطة بهذا الحساب.')
        return
      }
      authSession.setLogin(result, selectable[0])
      onLoggedIn()
    } catch (cause) { setError(appError(cause)) }
  }

  const selectTenant = async (tenant: TenantInfo) => {
    setError(null)
    try {
      const result = await login.mutateAsync({ tenantId: tenant.tenant_id })
      authSession.setLogin(result, tenant)
      onLoggedIn()
    } catch (cause) { setError(appError(cause)) }
  }

  const tenants = (response?.tenants || []).filter((tenant) => tenant.workspace_type === 'organizer' && tenant.membership_status === 'active')
  if (response) return <main className="auth-shell"><section className="auth-card"><Brand /><h1>اختر فريق التشغيل</h1><p>يُسمح بتطبيق البوابات داخل فرق التشغيل فقط.</p>{error && <ErrorNote text={error} />}{tenants.map((tenant) => <button key={tenant.tenant_id} className="tenant-option" disabled={login.isPending} onClick={() => void selectTenant(tenant)}><strong>{tenant.name}</strong><span>{tenant.role}</span></button>)}<button className="text-button" onClick={() => { setResponse(null); setError(null) }}>العودة لتسجيل الدخول</button></section></main>

  return <main className="auth-shell"><section className="auth-card"><Brand /><h1>دخول موظف البوابة</h1><p>استخدم حسابك الشخصي. لا توجد حسابات أو رموز بوابة مشتركة.</p><form onSubmit={(event) => void submit(event)}><label>البريد الإلكتروني<input type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></label><label>كلمة المرور<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>{error && <ErrorNote text={error} />}<button className="primary-button" disabled={login.isPending}>{login.isPending ? 'جارٍ التحقق…' : 'متابعة إلى وردياتي'}</button></form><p className="security-caption">صلاحية البوابة تُراجع من الخادم عند كل عملية.</p></section></main>
}

function Brand() { return <div className="brand"><span className="brand-mark">Q</span><div><b>Qentry Field</b><small>بوابات وورديات معتمدة</small></div></div> }
function ErrorNote({ text }: { text: string }) { return <p className="error-note" role="alert">{text}</p> }

type InstallPromptEvent = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }> }

function FieldApp({ onLogout }: { onLogout: () => void }) {
  const client = useQueryClient()
  const [selectedDate, setSelectedDate] = useState(() => isoDate(new Date()))
  const [selectedShift, setSelectedShift] = useState<FieldShift | null>(null)
  const [deviceName, setDeviceName] = useState(defaultDeviceName)
  const [networkOnline, setNetworkOnline] = useState(navigator.onLine)
  const [deviceSession, setDeviceSession] = useState(() => authSession.getDeviceSession())
  const [installPrompt, setInstallPrompt] = useState<InstallPromptEvent | null>(null)

  useEffect(() => {
    const sync = () => setNetworkOnline(navigator.onLine)
    addEventListener('online', sync); addEventListener('offline', sync)
    return () => { removeEventListener('online', sync); removeEventListener('offline', sync) }
  }, [])

  useEffect(() => {
    const capture = (event: Event) => { event.preventDefault(); setInstallPrompt(event as InstallPromptEvent) }
    addEventListener('beforeinstallprompt', capture)
    return () => removeEventListener('beforeinstallprompt', capture)
  }, [])

  useEffect(() => {
    if (deviceSession) return
    void authSession.restoreDeviceSession().then((restored) => {
      if (restored) setDeviceSession(restored)
    })
  }, [deviceSession])

  const shifts = useQuery({ queryKey: ['field-shifts', selectedDate], queryFn: () => fieldApi.shifts(selectedDate) })
  const startSession = useMutation({
    mutationFn: (shift: FieldShift) => fieldApi.startDeviceSession({
      shift_id: shift.shift_id, device_id: getFieldDeviceId(), device_name: deviceName,
      platform: navigator.userAgent.slice(0, 64), app_version: 'field-pwa/0.1.0',
    }),
    onSuccess: (session) => {
      authSession.setDeviceSession({ deviceSession: session, tenantId: authSession.tenantId || '' })
      setDeviceSession({ deviceSession: session, tenantId: authSession.tenantId || '' })
      setSelectedShift(null)
      void client.invalidateQueries({ queryKey: ['field-shifts'] })
    },
  })
  const closeSession = useMutation({
    mutationFn: () => fieldApi.closeDeviceSession(deviceSession!.deviceSession.id),
    onSuccess: async () => {
      // Closing revokes the server pack. Remove its encrypted local copy and
      // queue as well, so a handed-over device cannot retain stale QR values.
      const sessionId = deviceSession!.deviceSession.id
      const stored = await offlineStore.getPack(sessionId).catch(() => null)
      if (stored) await offlineStore.clearPack(sessionId, stored.pack.pack_id).catch(() => undefined)
      authSession.clearDeviceSession()
      setDeviceSession(null)
      void client.invalidateQueries({ queryKey: ['field-shifts'] })
    },
  })
  const canMoveBack = selectedDate > isoDate(new Date())
  const dateTitle = useMemo(() => dateFormatter.format(new Date(`${selectedDate}T12:00:00`)), [selectedDate])

  const logout = async () => { try { await fieldApi.logout() } catch { /* Local session must still be cleared. */ } finally { authSession.clearLogin(); onLogout() } }
  const install = async () => {
    if (!installPrompt) return
    await installPrompt.prompt()
    await installPrompt.userChoice
    setInstallPrompt(null)
  }

  if (deviceSession) return <ScannerConsole session={deviceSession.deviceSession} online={networkOnline} onClose={() => closeSession.mutate()} closing={closeSession.isPending} closeError={closeSession.error ? appError(closeSession.error) : null} />

  return <main className="field-shell"><header className="app-header"><Brand /><div className="header-actions"><span className={networkOnline ? 'network online' : 'network offline'}>{networkOnline ? 'متصل' : 'دون اتصال'}</span>{installPrompt && <button className="icon-button" title="تثبيت تطبيق البوابة" onClick={() => void install()}>↓</button>}<button className="icon-button" title="تسجيل الخروج" onClick={() => void logout()}>⇥</button></div></header><section className="welcome"><span>وردية ميدانية</span><h1>حفلاتي وبواباتي</h1><p>اختر وردية فعالة لبدء جلسة هذا الجهاز.</p></section><section className="date-switcher" aria-label="اختيار تاريخ"><button disabled={!canMoveBack} onClick={() => setSelectedDate(moveDate(selectedDate, -1))}>اليوم السابق</button><strong>{dateTitle}</strong><button onClick={() => setSelectedDate(moveDate(selectedDate, 1))}>اليوم التالي</button></section><section className="shift-list"><div className="section-heading"><h2>الورديات المسندة</h2>{shifts.isFetching && <span>تحديث…</span>}</div>{shifts.isLoading && <Loading />}{shifts.error && <ErrorNote text={appError(shifts.error)} />}{shifts.data?.length === 0 && <EmptyShifts />}{shifts.data?.map((shift) => <ShiftCard key={shift.shift_id} shift={shift} onSelect={() => setSelectedShift(shift)} />)}</section>{selectedShift && <StartSessionDialog shift={selectedShift} deviceName={deviceName} setDeviceName={setDeviceName} busy={startSession.isPending} error={startSession.error ? appError(startSession.error) : null} onStart={() => startSession.mutate(selectedShift)} onClose={() => setSelectedShift(null)} />}</main>
}

function ShiftCard({ shift, onSelect }: { shift: FieldShift; onSelect: () => void }) {
  const active = shift.can_start
  const label = shift.event_title_ar || shift.event_title
  return <article className="shift-card"><div className="shift-card__top"><span className={`status ${active ? 'status--active' : 'status--scheduled'}`}>{active ? 'متاحة الآن' : 'مجدولة'}</span><span className="role">{shift.shift_role === 'supervisor' ? 'مشرف بوابة' : 'مسّاح'}</span></div><h3>{label}</h3><p className="gate-name">{shift.gate_name_ar || shift.gate_name}</p><div className="shift-meta"><span>{timeFormatter.format(new Date(shift.starts_at))} — {timeFormatter.format(new Date(shift.ends_at))}</span><span>{shift.timezone}</span></div><button className="primary-button" disabled={!active} onClick={onSelect}>{active ? 'بدء جلسة البوابة' : 'تبدأ ضمن وقت الوردية'}</button></article>
}

function StartSessionDialog({ shift, deviceName, setDeviceName, busy, error, onStart, onClose }: { shift: FieldShift; deviceName: string; setDeviceName: (value: string) => void; busy: boolean; error: string | null; onStart: () => void; onClose: () => void }) {
  return <div className="dialog-backdrop" role="presentation"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="session-title"><button className="dialog-close" aria-label="إغلاق" onClick={onClose}>×</button><span className="eyebrow">جلسة جهاز</span><h2 id="session-title">{shift.gate_name_ar || shift.gate_name}</h2><p>ستكون هذه الجلسة مرتبطة بهذه البوابة فقط. لا يمكن تشغيل جهاز ثانٍ للوردية نفسها دون إلغاء الجلسة الحالية من المشرف.</p><label>اسم الجهاز<input value={deviceName} maxLength={160} onChange={(event) => setDeviceName(event.target.value)} /></label>{error && <ErrorNote text={error} />}<button className="primary-button" disabled={busy || !deviceName.trim()} onClick={onStart}>{busy ? 'جارٍ تأمين الجلسة…' : 'تأكيد وبدء الجلسة'}</button></section></div>
}

function Loading() { return <div className="loading"><span /> جارٍ تحميل وردياتك…</div> }
function EmptyShifts() { return <div className="empty"><strong>لا توجد ورديات مسندة لهذا اليوم.</strong><p>يجب أن يسندك مدير الحفل إلى وردية بوابة فعالة قبل السماح لك بالمسح.</p></div> }

function Root() {
  const [authenticated, setAuthenticated] = useState(Boolean(authSession.accessToken && authSession.tenantId))
  useEffect(() => { installServiceWorker() }, [])
  return authenticated ? <FieldApp onLogout={() => setAuthenticated(false)} /> : <LoginScreen onLoggedIn={() => setAuthenticated(true)} />
}

export default function App() { return <QueryClientProvider client={queryClient}><Root /></QueryClientProvider> }
