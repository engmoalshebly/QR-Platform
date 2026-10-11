import { LimitErrorNotice } from '@components/LimitErrorNotice'
import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Building2, CalendarDays, Check, Clock, Mail, MapPin, Plus, Users, X,
  Search, Activity, ListChecks, CheckCircle2, ChevronLeft, ChevronRight
} from 'lucide-react'
import { WorkspaceShell } from '@features/workspace/components/WorkspaceShell'
import { bookingsAPI, type Booking, type BookingCreate, type OrganizerTeam } from '../api/bookingsApi'
import { usersAPI } from '@features/users/api/usersApi'
import { eventsAPI } from '@features/events/api/eventsApi'
import { authAPI } from '@features/auth/api/authApi'
import { operationsAPI, type OperationSummary } from '@features/operations/api/operationsApi'
import { dashboardAPI } from '@features/dashboard/api/dashboardApi'
import { ConfirmDialog } from '@components/ConfirmDialog'
import { toast } from '@components/toast'
import { Link, useSearchParams } from 'react-router-dom'
import { PERM, usePermission } from '@shared/permissions'
import { useAuthStore } from '@features/auth/store/authStore'
import './bookings.css'
import './booking-event.css'

const statusLabels: Record<string, string> = {
  pending: 'قيد الانتظار', needs_information: 'يحتاج معلومات', accepted: 'مقبول',
  in_progress: 'قيد التنفيذ', rejected: 'مرفوض', cancelled: 'ملغي',
  completed: 'مكتمل', reopened: 'أعيد فتحه',
}

const operationStatusLabels: Record<string, string> = {
  planning: 'قيد التخطيط',
  ready: 'جاهز للتنفيذ',
  in_progress: 'قيد التنفيذ',
  completed: 'مكتمل',
  cancelled: 'ملغي',
}

function operationDate(value: string) {
  return new Date(value).toLocaleDateString('ar-SA-u-ca-gregory', {
    weekday: 'short', day: 'numeric', month: 'short', year: 'numeric',
  })
}

function operationTime(value: string) {
  return new Date(value).toLocaleTimeString('ar-SA-u-ca-gregory', {
    hour: 'numeric', minute: '2-digit',
  })
}

function calendarDateKey(value: Date | string) {
  const date = typeof value === 'string' ? new Date(value) : value
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}


function BookingDialog({ team, close, saved }: { team: OrganizerTeam; close: () => void; saved: () => void }) {
  const [form, setForm] = useState<BookingCreate>({
    provider_tenant_id: team.tenant_id, event_id: '', contact_phone: '', services: '', notes: '',
  })
  const [error, setError] = useState<unknown>(null)
  const events = useQuery({ queryKey: ['booking-source-events'], queryFn: () => eventsAPI.list() })
  const profile = useQuery({ queryKey: ['auth-me'], queryFn: authAPI.me })
  const selectedEvent = events.data?.find(event => event.id === form.event_id)
  const profilePhone = profile.data?.phone
  
  useEffect(() => {
    if (profilePhone && !form.contact_phone) setForm(value => ({ ...value, contact_phone: profilePhone }))
  }, [profilePhone, form.contact_phone])
  
  const mutation = useMutation({
    mutationFn: bookingsAPI.create,
    onSuccess: saved,
    onError: (e: any) => setError(e),
  })
  
  const set = (key: keyof BookingCreate, value: string | number) => setForm(v => ({ ...v, [key]: value }))
  
  const submit = (e: React.FormEvent) => {
    e.preventDefault(); setError('')
    mutation.mutate(form)
  }
  
  return <div className="booking-overlay" onClick={close}><form className="booking-dialog" onSubmit={submit} onClick={e => e.stopPropagation()}>
    <div className="booking-dialog__head"><div><small>طلب حجز</small><h2>{team.name}</h2></div><button type="button" onClick={close}><X /></button></div>
    <LimitErrorNotice error={error} />
    <div className="booking-form-grid">
      <label className="wide">اختر الحفل
        <select required value={form.event_id} onChange={e => set('event_id', e.target.value)} disabled={events.isLoading}>
          <option value="">{events.isLoading ? 'جاري تحميل حفلاتك...' : 'اختر حفلاً من أحداث المؤسسة'}</option>
          {events.data?.filter(event => !event.deleted_at).map(event => <option key={event.id} value={event.id}>
            {event.title} — {new Date(event.start_date).toLocaleDateString('ar')}
          </option>)}
        </select>
      </label>
      {events.isError && <div className="booking-error wide">تعذر تحميل قائمة الأحداث. حاول تحديث الصفحة.</div>}
      {selectedEvent && <div className="booking-event-preview wide">
        <div><strong>{selectedEvent.title}</strong><span className={`booking-event-status status-${selectedEvent.status}`}>{selectedEvent.status}</span></div>
        <p>{selectedEvent.description || 'سيتم إرسال جميع بيانات هذا الحفل إلى مدير الفريق.'}</p>
        <dl>
          <div><dt>البداية</dt><dd>{new Date(selectedEvent.start_date).toLocaleString('ar')}</dd></div>
          <div><dt>النهاية</dt><dd>{selectedEvent.end_date ? new Date(selectedEvent.end_date).toLocaleString('ar') : 'غير محددة (يُحسب 4 ساعات)'}</dd></div>
          <div><dt>المكان</dt><dd>{[selectedEvent.venue_name, selectedEvent.venue_address, selectedEvent.venue_city, selectedEvent.venue_country].filter(Boolean).join('، ') || 'غير محدد'}</dd></div>
          <div><dt>السعة</dt><dd>{selectedEvent.capacity || selectedEvent.vip_quota + selectedEvent.normal_quota || 1} ضيف</dd></div>
        </dl>
      </div>}
      <label className="wide">رقم التواصل *
        <input required type="tel" minLength={8} dir="ltr" value={form.contact_phone} onChange={e => set('contact_phone', e.target.value)} placeholder="05xxxxxxxx" />
        <small>سيُحفظ الرقم في حسابك تلقائيًا ويصل إلى مدير الفريق مع الطلب.</small>
      </label>
      <label className="wide">الخدمات المطلوبة<textarea value={form.services} onChange={e => set('services', e.target.value)} /></label>
      <label className="wide">ملاحظات إضافية<textarea value={form.notes} onChange={e => set('notes', e.target.value)} /></label>
    </div>
    <div className="booking-dialog__actions"><button type="button" className="btn-secondary" onClick={close}>إلغاء</button><button disabled={mutation.isPending} className="btn-primary">{mutation.isPending ? 'جارٍ الإرسال...' : 'إرسال طلب الحجز'}</button></div>
  </form></div>
}

function BookingCard({ booking, provider, respond, complete, canRespond = true, canComplete = true }: { booking: Booking; provider: boolean; respond?: (id: string, action: 'accepted'|'rejected'|'needs_information') => void; complete?: (id: string) => void; canRespond?: boolean; canComplete?: boolean }) {
  const counterpart = provider ? booking.requester_name : booking.provider_name

  return <article className={`booking-card booking-card--${provider ? 'inbox' : 'sent'}`}>
    <header className="booking-card__header">
      <div className="booking-card__requester">
        <span>{provider ? 'طلب وارد من المؤسسة' : 'فريق التنظيم'}</span>
        <strong><Building2 size={15} />{counterpart}</strong>
      </div>
      <span className={`booking-status status-${booking.status}`}>{statusLabels[booking.status]}</span>
    </header>

    <div className="booking-card__event">
      <div className="booking-card__event-icon"><CalendarDays size={20} /></div>
      <div>
        <span>{booking.event_type || 'فعالية'}</span>
        <h3>{booking.title}</h3>
        <p>{booking.event_description || 'لم تُضف المؤسسة وصفًا إضافيًا للحفل.'}</p>
      </div>
    </div>

    <dl className="booking-card__facts">
      <div><dt><CalendarDays size={15} />البداية</dt><dd>{new Date(booking.starts_at).toLocaleString('ar')}</dd></div>
      <div><dt><Clock size={15} />النهاية</dt><dd>{new Date(booking.ends_at).toLocaleString('ar')}</dd></div>
      <div><dt><Users size={15} />الضيوف</dt><dd>{booking.guest_count} ضيف</dd></div>
      <div><dt><MapPin size={15} />الموقع</dt><dd>{booking.location || 'لم يُحدّد بعد'}</dd></div>
    </dl>

    <div className="booking-card__details">
      {(booking.services || booking.notes) && <div className="booking-card__brief">
        {booking.services && <div><span>الخدمات المطلوبة</span><p>{booking.services}</p></div>}
        {booking.notes && <div><span>ملاحظات المؤسسة</span><p>{booking.notes}</p></div>}
      </div>}
      {booking.event_map_url && <a className="booking-map-link" href={booking.event_map_url} target="_blank" rel="noreferrer"><MapPin size={15} />فتح موقع الحفل</a>}
      {provider && <div className="booking-contact"><div><span>جهة التواصل</span><strong>{booking.contact_name}</strong></div><div><span>الهاتف</span><strong dir="ltr">{booking.contact_phone}</strong></div>{booking.contact_email && <div><span>البريد الإلكتروني</span><strong dir="ltr"><Mail size={14} />{booking.contact_email}</strong></div>}</div>}
      {booking.response_note && <div className="booking-note">{booking.response_note}</div>}
    </div>

    {provider && canRespond && ['pending','needs_information'].includes(booking.status) && <footer className="booking-actions">
      <button className="accept" onClick={() => respond?.(booking.id, 'accepted')}><Check />قبول وإسناد الحفل</button>
      <button onClick={() => respond?.(booking.id, 'needs_information')}><Mail />طلب معلومات</button>
      <button className="reject" onClick={() => respond?.(booking.id, 'rejected')}><X />رفض</button>
    </footer>}
    {provider && canComplete && booking.status === 'accepted' && <footer className="booking-actions booking-actions--complete"><button className="accept" onClick={() => complete?.(booking.id)}><Check />إكمال الحفل</button></footer>}
  </article>
}

function BookingRequestDrawer({ booking, close, respond, start, complete, canRespond, canComplete }: {
  booking: Booking
  close: () => void
  respond: (booking: Booking, action: 'accepted'|'rejected'|'needs_information') => void
  start: (booking: Booking) => void
  complete: (booking: Booking) => void
  canRespond: boolean
  canComplete: boolean
}) {
  const canTakeAction = canRespond && ['pending', 'needs_information'].includes(booking.status)
  const canStart = canComplete && ['accepted', 'reopened'].includes(booking.status)
  const canFinish = canComplete && booking.status === 'in_progress'

  return <div className="booking-request-drawer__overlay" onClick={close} role="presentation">
    <aside className="booking-request-drawer" onClick={event => event.stopPropagation()} aria-label="تفاصيل طلب الحفل">
      <header className="booking-request-drawer__head">
        <div><span>طلب وارد من {booking.requester_name}</span><h2>{booking.title}</h2></div>
        <div className="booking-request-drawer__head-actions"><span className={`booking-status status-${booking.status}`}>{statusLabels[booking.status]}</span><button type="button" onClick={close} aria-label="إغلاق التفاصيل"><X size={19} /></button></div>
      </header>

      <div className="booking-request-drawer__body">
        <section className="booking-request-drawer__summary">
          <div className="booking-request-drawer__event-icon"><CalendarDays size={22} /></div>
          <div><span>{booking.event_type || 'فعالية'}</span><p>{booking.event_description || 'لم تضف المؤسسة وصفًا إضافيًا للحفل.'}</p></div>
        </section>

        <dl className="booking-request-drawer__facts">
          <div><dt>بداية الحفل</dt><dd><CalendarDays size={15} />{new Date(booking.starts_at).toLocaleString('ar')}</dd></div>
          <div><dt>نهاية الحفل</dt><dd><Clock size={15} />{new Date(booking.ends_at).toLocaleString('ar')}</dd></div>
          <div><dt>عدد الضيوف</dt><dd><Users size={15} />{booking.guest_count} ضيف</dd></div>
          <div><dt>الموقع</dt><dd><MapPin size={15} />{booking.location || 'لم يُحدّد بعد'}</dd></div>
        </dl>

        <section className="booking-request-drawer__section">
          <span>جهة التواصل</span>
          <strong>{booking.contact_name}</strong>
          <div className="booking-request-drawer__contact"><b dir="ltr">{booking.contact_phone}</b>{booking.contact_email && <b dir="ltr"><Mail size={14} />{booking.contact_email}</b>}</div>
        </section>

        {booking.services && <section className="booking-request-drawer__section"><span>الخدمات المطلوبة</span><p>{booking.services}</p></section>}
        {booking.notes && <section className="booking-request-drawer__section"><span>ملاحظات المؤسسة</span><p>{booking.notes}</p></section>}
        {booking.response_note && <section className="booking-request-drawer__section booking-request-drawer__section--note"><span>ملاحظة على الطلب</span><p>{booking.response_note}</p></section>}
        {booking.event_map_url && <a className="booking-map-link" href={booking.event_map_url} target="_blank" rel="noreferrer"><MapPin size={15} />فتح موقع الحفل على الخريطة</a>}
      </div>

      {(canTakeAction || canStart || canFinish) && <footer className="booking-request-drawer__actions">
        {canTakeAction && <><button className="accept" onClick={() => respond(booking, 'accepted')}><Check />قبول وإسناد الحفل</button><button onClick={() => respond(booking, 'needs_information')}><Mail />طلب معلومات</button><button className="reject" onClick={() => respond(booking, 'rejected')}><X />رفض</button></>}
        {!canTakeAction && canStart && <button className="accept" onClick={() => start(booking)}><Activity />بدء تنفيذ الحفل</button>}
        {!canTakeAction && canFinish && <button className="accept" onClick={() => complete(booking)}><Check />إكمال الحفل</button>}
      </footer>}
    </aside>
  </div>
}

function OperationPreviewModal({ operation, close, canComplete, start, complete }: {
  operation: OperationSummary
  close: () => void
  canComplete: boolean
  start: (operation: OperationSummary) => void
  complete: (operation: OperationSummary) => void
}) {
  const canStart = canComplete && Boolean(operation.booking_id) && ['planning', 'ready'].includes(operation.status)
  const canFinish = canComplete && Boolean(operation.booking_id) && operation.status === 'in_progress'

  return <div className="booking-request-drawer__overlay" onClick={close} role="presentation">
    <aside className="booking-request-drawer operation-preview-modal" onClick={event => event.stopPropagation()} aria-label="ملخص الحفل">
      <header className="booking-request-drawer__head">
        <div><span>حفل مُسنَد من {operation.requester_name}</span><h2>{operation.title}</h2></div>
        <div className="booking-request-drawer__head-actions"><span className={`operation-status operation-status--${operation.status}`}>{operationStatusLabels[operation.status] || operation.status}</span><button type="button" onClick={close} aria-label="إغلاق التفاصيل"><X size={19} /></button></div>
      </header>

      <div className="booking-request-drawer__body">
        <section className="booking-request-drawer__summary">
          <div className="booking-request-drawer__event-icon"><CalendarDays size={22} /></div>
          <div><span>مساحة التنفيذ</span><p>متابعة تنفيذ الحفل من التخطيط وتوزيع الفريق حتى الإغلاق.</p></div>
        </section>
        <dl className="booking-request-drawer__facts">
          <div><dt>موعد الحفل</dt><dd><CalendarDays size={15} />{operationDate(operation.starts_at)} · {operationTime(operation.starts_at)}</dd></div>
          <div><dt>الموقع</dt><dd><MapPin size={15} />{operation.location || 'لم يُحدّد بعد'}</dd></div>
          <div><dt>الدعوات</dt><dd><Users size={15} />{operation.guest_count} دعوة</dd></div>
          <div><dt>المهام</dt><dd><ListChecks size={15} />{operation.tasks_done} من {operation.tasks_count} مكتملة</dd></div>
        </dl>
        <section className="operation-preview-modal__progress"><div><span>تقدّم التنفيذ</span><strong>{operation.progress || 0}%</strong></div><i><b style={{ width: `${operation.progress || 0}%` }} /></i></section>
      </div>

      <footer className="booking-request-drawer__actions operation-preview-modal__actions">
        <Link to={`/team-events/${operation.id}`} onClick={close}>إدارة الحفل <ChevronLeft size={16} /></Link>
        {canStart && <button onClick={() => start(operation)}><Activity />بدء تنفيذ الحفل</button>}
        {canFinish && <button onClick={() => complete(operation)}><Check />إكمال الحفل</button>}
      </footer>
    </aside>
  </div>
}

export default function BookingHubPage() {
  const qc = useQueryClient()
  const userId = useAuthStore(s => s.user?.id)
  const currentTenantId = useAuthStore(s => s.currentTenantId)
  const setTenant = useAuthStore(s => s.setTenant)
  const [selectedTeam, setSelectedTeam] = useState<OrganizerTeam | null>(null)
  const [selectedInboxBooking, setSelectedInboxBooking] = useState<Booking | null>(null)
  const [selectedOperation, setSelectedOperation] = useState<OperationSummary | null>(null)
  const [searchParams] = useSearchParams()
  const providerTab = (searchParams.get('tab') || 'analytics') as 'analytics'|'groups'|'requests'|'events'|'calendar'|'tasks'|'guests'|'attendance'|'files'|'notifications'|'reports'
  const canCreateBookings = usePermission(PERM.BOOKINGS_CREATE)
  const canManageBookings = usePermission(PERM.BOOKINGS_MANAGE)
  const canRespondBookings = usePermission(PERM.BOOKINGS_RESPOND)
  


  // Events tab filters
  const [eventSearch, setEventSearch] = useState('')
  const [eventDateFilter, setEventDateFilter] = useState<'all'|'today'|'week'|'upcoming'>('all')
  const [eventStatusFilter, setEventStatusFilter] = useState<'all'|'active'|'completed'|'cancelled'>('all')
  const [calendarCursor, setCalendarCursor] = useState(() => new Date(new Date().getFullYear(), new Date().getMonth(), 1))
  const [selectedCalendarDay, setSelectedCalendarDay] = useState(() => calendarDateKey(new Date()))

  const context = useQuery({
    queryKey: ['booking-context', userId ?? 'anonymous', currentTenantId ?? 'none'],
    queryFn: bookingsAPI.context,
    enabled: Boolean(userId),
    retry: false,
  })
  const isProvider = !!context.data?.is_team_manager
  const providerTenantId = context.data?.team_tenant_id || null
  const teamTenantReady = !isProvider || !providerTenantId || providerTenantId === currentTenantId

  useEffect(() => {
    if (providerTenantId && providerTenantId !== currentTenantId) {
      setTenant(providerTenantId)
      qc.invalidateQueries()
    }
  }, [providerTenantId, currentTenantId, setTenant, qc])
  
  const teams = useQuery({ queryKey: ['organizer-teams'], queryFn: bookingsAPI.teams, enabled: context.isSuccess && !isProvider })
  const sent = useQuery({ queryKey: ['bookings-sent'], queryFn: bookingsAPI.sent, enabled: context.isSuccess && !isProvider })
  
  const inbox = useQuery({ queryKey: ['bookings-inbox', currentTenantId], queryFn: bookingsAPI.inbox, enabled: context.isSuccess && isProvider && teamTenantReady })
  // const analytics = useQuery({ queryKey: ['booking-analytics'], queryFn: bookingsAPI.analytics, enabled: context.isSuccess && isProvider })
  
  const providerDashboard = useQuery({
    queryKey: ['provider-dashboard', currentTenantId],
    queryFn: () => dashboardAPI.provider(),
    enabled: context.isSuccess && isProvider && teamTenantReady,
    refetchInterval: 15000 // auto-refresh stats every 15 seconds
  })

  const operations = useQuery({
    queryKey: ['operations', currentTenantId],
    queryFn: operationsAPI.list,
    enabled: context.isSuccess && isProvider && teamTenantReady,
    // Directly assigned institution events are created in the other workspace.
    // Poll briefly so an already-open team board receives them without reload.
    refetchInterval: 10_000,
  })
  const groups = useQuery({ queryKey: ['booking-groups', currentTenantId], queryFn: bookingsAPI.groups, enabled: context.isSuccess && isProvider && teamTenantReady })
  const members = useQuery({ queryKey: ['booking-team-members', currentTenantId], queryFn: usersAPI.list, enabled: context.isSuccess && isProvider && teamTenantReady })
  
  const [respondState, setRespondState] = useState<{ booking: Booking; action: 'accepted'|'rejected'|'needs_information' } | null>(null)
  const [respondNote, setRespondNote] = useState('')
  const [completeTarget, setCompleteTarget] = useState<{ id: string; title: string } | null>(null)
  const [groupDialog, setGroupDialog] = useState(false)
  const [groupName, setGroupName] = useState('')
  
  const response = useMutation({
    mutationFn: ({ id, action, note }: { id: string; action: 'accepted'|'rejected'|'needs_information'; note?: string }) =>
      bookingsAPI.respond(id, action, note),
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({ queryKey: ['bookings-inbox'] })
      qc.invalidateQueries({ queryKey: ['booking-analytics'] })
      qc.invalidateQueries({ queryKey: ['operations'] })
      qc.invalidateQueries({ queryKey: ['provider-dashboard'] })
      const labels = { accepted: 'تم قبول الطلب', rejected: 'تم رفض الطلب', needs_information: 'تم طلب المعلومات' }
      toast.success(labels[vars.action])
      setRespondState(null); setRespondNote(''); setSelectedInboxBooking(null)
    },
    onError: (e: any) => toast.apiError('فشلت العملية', e),
  })
  
  const createGroup = useMutation({
    mutationFn: bookingsAPI.createGroup,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['booking-groups'] }); toast.success('تمت إضافة المجموعة'); setGroupDialog(false); setGroupName('') },
    onError: (e: any) => toast.apiError('تعذرت الإضافة', e),
  })

  const start = useMutation({
    mutationFn: bookingsAPI.start,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['bookings-inbox'] })
      qc.invalidateQueries({ queryKey: ['booking-analytics'] })
      qc.invalidateQueries({ queryKey: ['operations'] })
      qc.invalidateQueries({ queryKey: ['provider-dashboard'] })
      toast.success('بدأ تنفيذ الحفل')
      setSelectedInboxBooking(null); setSelectedOperation(null)
    },
    onError: (e: any) => toast.apiError('تعذر بدء التنفيذ', e),
  })
  
  const complete = useMutation({
    mutationFn: bookingsAPI.complete,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['bookings-inbox'] })
      qc.invalidateQueries({ queryKey: ['booking-analytics'] })
      qc.invalidateQueries({ queryKey: ['operations'] })
      qc.invalidateQueries({ queryKey: ['provider-dashboard'] })
      toast.success('تم إكمال الحفل')
      setCompleteTarget(null); setSelectedInboxBooking(null); setSelectedOperation(null)
    },
    onError: (e: any) => toast.apiError('تعذر الإكمال', e),
  })
  
  const assignableOperations = useMemo(
    () => (operations.data || []).filter(operation => !['completed', 'closed', 'cancelled'].includes(operation.status)),
    [operations.data],
  )
  const calendarEntries = useMemo(() => {
    const operationEntries = (operations.data || []).filter(operation => operation.status !== 'cancelled').map(operation => ({
      id: `operation-${operation.id}`,
      operationId: operation.id,
      title: operation.title,
      startsAt: operation.starts_at,
      status: operation.status,
      kind: 'operation' as const,
      detail: operation.requester_name,
    }))
    const assignedBookings = new Set((operations.data || []).map(operation => operation.booking_id).filter(Boolean))
    const requestEntries = (inbox.data || []).filter(booking =>
      ['pending', 'needs_information'].includes(booking.status) && !assignedBookings.has(booking.id),
    ).map(booking => ({
      id: `request-${booking.id}`,
      bookingId: booking.id,
      title: booking.title,
      startsAt: booking.starts_at,
      status: booking.status,
      kind: 'request' as const,
      detail: booking.requester_name,
    }))
    return [...operationEntries, ...requestEntries].sort((a, b) => new Date(a.startsAt).getTime() - new Date(b.startsAt).getTime())
  }, [operations.data, inbox.data])
  const calendarMonthCells = useMemo(() => {
    const first = new Date(calendarCursor.getFullYear(), calendarCursor.getMonth(), 1)
    const gridStart = new Date(first.getFullYear(), first.getMonth(), 1 - first.getDay())
    return Array.from({ length: 42 }, (_, index) => {
      const date = new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate() + index)
      const key = calendarDateKey(date)
      return { date, key, inCurrentMonth: date.getMonth() === calendarCursor.getMonth(), entries: calendarEntries.filter(entry => calendarDateKey(entry.startsAt) === key) }
    })
  }, [calendarCursor, calendarEntries])
  const selectedDayEntries = useMemo(() => calendarEntries.filter(entry => calendarDateKey(entry.startsAt) === selectedCalendarDay), [calendarEntries, selectedCalendarDay])
  const selectedDayConfirmed = selectedDayEntries.filter(entry => entry.kind === 'operation' && !['completed', 'cancelled'].includes(entry.status))
  const calendarMonthLabel = useMemo(() => new Intl.DateTimeFormat('ar-SA-u-ca-gregory', { month: 'long', year: 'numeric' }).format(calendarCursor), [calendarCursor])
  // const managedEvents = operations.data || []

  // Events Filtering logic
  const filteredEvents = useMemo(() => {
    let list = operations.data || []
    
    // 1. Search Query
    if (eventSearch.trim()) {
      const query = eventSearch.toLowerCase()
      list = list.filter(op => 
        op.title.toLowerCase().includes(query) || 
        op.requester_name.toLowerCase().includes(query) ||
        (op.location || '').toLowerCase().includes(query)
      )
    }

    // 2. Status Filter
    if (eventStatusFilter !== 'all') {
      if (eventStatusFilter === 'active') {
        list = list.filter(op => ['planning', 'ready', 'in_progress'].includes(op.status))
      } else {
        list = list.filter(op => op.status === eventStatusFilter)
      }
    }

    // 3. Date Filter
    if (eventDateFilter !== 'all') {
      const now = new Date()
      now.setHours(0,0,0,0)
      
      list = list.filter(op => {
        const evDate = new Date(op.starts_at)
        evDate.setHours(0,0,0,0)
        
        if (eventDateFilter === 'today') {
          return evDate.getTime() === now.getTime()
        } else if (eventDateFilter === 'week') {
          const nextWeek = new Date(now)
          nextWeek.setDate(now.getDate() + 7)
          return evDate >= now && evDate <= nextWeek
        } else if (eventDateFilter === 'upcoming') {
          return evDate >= now
        }
        return true
      })
    }

    return list
  }, [operations.data, eventSearch, eventStatusFilter, eventDateFilter])

  if (context.isLoading || (isProvider && !teamTenantReady)) return <WorkspaceShell title="الفرق والحجوزات" subtitle="جارٍ التحميل"><div className="booking-empty">جارٍ التحميل...</div></WorkspaceShell>

  if (!isProvider) return <WorkspaceShell title="فرق التنظيم" subtitle="استعرض الجهات المعتمدة وأرسل طلب حجز متكامل">
    <div className="booking-tabs-title"><h2>الفرق المعتمدة</h2><span>{teams.data?.length || 0} فريق</span></div>
    <div className="organizer-grid">{teams.data?.map(team => <article className="organizer-card" key={team.tenant_id}>
      <div className="organizer-icon"><Building2 /></div><h3>{team.name}</h3><span>{team.org_type || 'تنظيم فعاليات'}</span><p>{team.description || 'فريق تنظيم معتمد من إدارة المنصة'}</p>
      <div className="organizer-meta"><span><MapPin />{[team.city, team.country].filter(Boolean).join('، ') || 'غير محدد'}</span><span><Check />{team.completed_bookings} حجوزات مكتملة</span></div>
      {canCreateBookings && <button onClick={() => setSelectedTeam(team)}><CalendarDays /> طلب حجز الفريق</button>}
    </article>)}</div>
    {!teams.data?.length && <div className="booking-empty">لا توجد فرق تنظيم معتمدة حالياً.</div>}
    <div className="booking-tabs-title"><h2>طلباتي</h2><span>{sent.data?.length || 0} طلب</span></div>
    <div className="booking-list">{sent.data?.map(b => <BookingCard key={b.id} booking={b} provider={false} />)}</div>
    {canCreateBookings && selectedTeam && <BookingDialog team={selectedTeam} close={() => setSelectedTeam(null)} saved={() => { setSelectedTeam(null); qc.invalidateQueries({ queryKey: ['bookings-sent'] }) }} />}
  </WorkspaceShell>

  const pData = providerDashboard.data || {}
  const bookingFunnel = pData.booking_funnel || {}
  const scanQuality = pData.scan_quality || {}
  const totalRequests = bookingFunnel.total_requests || 0
  const activeOperations = pData.operations?.active_operations || 0
  const completedOperations = pData.operations?.completed_operations || 0
  const completionRate = pData.tasks?.completion_rate || 0
  const attendanceRate = pData.attendance?.attendance_rate || 0
  const operationalHealth = Math.round((Number(completionRate) + Number(attendanceRate) + Number(scanQuality.scan_success_rate || 0)) / 3)

  return <WorkspaceShell title="لوحة فريق التنظيم" subtitle="مساحة تشغيل مستقلة لإدارة الطلبات والحفلات والفريق">

    {providerTab === 'analytics' && (
      <div className="provider-dashboard-container">

            <div className="analytics-command">
              <div>
                <small>مركز تحليلات فريق التنظيم</small>
                <h2>صحة التشغيل {operationalHealth}%</h2>
                <p>قراءة موحدة لأداء الطلبات، إنجاز المهام، الحضور، جودة المسح، وحركة الحفلات القادمة.</p>
              </div>
              <div className="analytics-command__score">
                <strong>{operationalHealth}%</strong>
                <span>مؤشر التشغيل العام</span>
                <div className="progress-bar-wrapper"><div className="progress-bar-fill" style={{ width: `${operationalHealth}%` }} /></div>
              </div>
            </div>

            <div className="analytics-kpi-strip">
              <article><span>إجمالي الطلبات</span><strong>{totalRequests}</strong><small>{bookingFunnel.pending_requests || 0} بانتظار الرد</small></article>
              <article><span>معدل القبول</span><strong>{bookingFunnel.acceptance_rate || 0}%</strong><small>{bookingFunnel.accepted_requests || 0} مقبول</small></article>
              <article><span>متوسط الرد</span><strong>{bookingFunnel.avg_response_hours || 0}س</strong><small>من وصول الطلب حتى القرار</small></article>
              <article><span>الحفلات النشطة</span><strong>{activeOperations}</strong><small>{completedOperations} مكتملة</small></article>
              <article><span>إنجاز المهام</span><strong>{completionRate}%</strong><small>{pData.tasks?.overdue_tasks || 0} متأخرة</small></article>
              <article><span>جودة المسح</span><strong>{scanQuality.scan_success_rate || 0}%</strong><small>{scanQuality.total_scans || 0} عملية مسح</small></article>
            </div>

            <div className="analytics-funnel-grid">
              <section className="dashboard-section">
                <h3>مسار طلبات الحجز</h3>
                <div className="funnel-bars">
                  {[
                    ['قيد الانتظار', bookingFunnel.pending_requests || 0, '#fbbf24'],
                    ['يحتاج معلومات', bookingFunnel.needs_information_requests || 0, '#60a5fa'],
                    ['مقبول', bookingFunnel.accepted_requests || 0, '#34d399'],
                    ['مكتمل', bookingFunnel.completed_requests || 0, '#a7f3d0'],
                    ['مرفوض', bookingFunnel.rejected_requests || 0, '#f87171'],
                  ].map(([label,value,color]) => {
                    const pct = totalRequests ? Math.round((Number(value) * 100) / totalRequests) : 0
                    return <div className="funnel-row" key={String(label)}>
                      <div><span>{label}</span><b>{value}</b></div>
                      <div className="funnel-track"><i style={{ width: `${pct}%`, background: String(color) }} /></div>
                    </div>
                  })}
                </div>
              </section>

              <section className="dashboard-section">
                <h3>توزيع أولوية المهام</h3>
                <div className="priority-grid">
                  {(pData.task_priority_breakdown || []).map((item: any) => (
                    <article key={item.priority}>
                      <span>{item.priority}</span>
                      <strong>{item.open}</strong>
                      <small>{item.done} مكتملة من {item.total}</small>
                    </article>
                  ))}
                  {!(pData.task_priority_breakdown || []).length && <div className="booking-empty">لا توجد مهام مصنفة حتى الآن.</div>}
                </div>
              </section>
            </div>


            {/* Analytics Stats Cards Grid */}
            <div className="analytics-grid">
              {/* Operations Stats */}
              <div className="analytics-card">
                <div className="analytics-card__header">
                  <h3>العمليات والمشاريع</h3>
                  <div className="analytics-card__icon"><Activity /></div>
                </div>
                <div className="card-stats-list">
                  <div className="stat-item"><span>نشطة</span><strong>{pData.operations?.active_operations || 0}</strong></div>
                  <div className="stat-item"><span>مكتملة</span><strong>{pData.operations?.completed_operations || 0}</strong></div>
                </div>
                <div className="progress-container">
                  <span>متوسط إنجاز الحفلات الجارية</span>
                  <div className="progress-bar-wrapper">
                    <div className="progress-bar-fill" style={{ width: `${pData.operations?.avg_progress || 0}%` }} />
                  </div>
                  <strong>{pData.operations?.avg_progress || 0}%</strong>
                </div>
              </div>

              {/* Tasks Stats */}
              <div className="analytics-card">
                <div className="analytics-card__header">
                  <h3>المهام التنفيذية</h3>
                  <div className="analytics-card__icon"><ListChecks /></div>
                </div>
                <div className="card-stats-list">
                  <div className="stat-item"><span>إجمالي المهام</span><strong>{pData.tasks?.total_tasks || 0}</strong></div>
                  <div className="stat-item"><span>مكتملة</span><strong>{pData.tasks?.completed_tasks || 0}</strong></div>
                  <div className="stat-item"><span>قيد التنفيذ</span><strong>{pData.tasks?.in_progress_tasks || 0}</strong></div>
                  <div className="stat-item"><span>متأخرة</span><strong style={{ color: (pData.tasks?.overdue_tasks || 0) > 0 ? '#f87171' : '#fff' }}>{pData.tasks?.overdue_tasks || 0}</strong></div>
                </div>
                <div className="progress-container">
                  <span>معدل إكمال المهام</span>
                  <div className="progress-bar-wrapper">
                    <div className="progress-bar-fill" style={{ width: `${pData.tasks?.completion_rate || 0}%`, background: '#34d399' }} />
                  </div>
                  <strong>{pData.tasks?.completion_rate || 0}%</strong>
                </div>
              </div>

              {/* Attendance Stats */}
              <div className="analytics-card">
                <div className="analytics-card__header">
                  <h3>الحضور والمدعوين</h3>
                  <div className="analytics-card__icon"><Users /></div>
                </div>
                <div className="card-stats-list">
                  <div className="stat-item"><span>التذاكر المصدرة</span><strong>{pData.attendance?.total_invitations || 0}</strong></div>
                  <div className="stat-item"><span>تم التحضير</span><strong>{pData.attendance?.checked_in_count || 0}</strong></div>
                  <div className="stat-item"><span>حضور VIP</span><strong>{pData.attendance?.vip_checked_in || 0} / {pData.attendance?.vip_total || 0}</strong></div>
                  <div className="stat-item"><span>حضور عادي</span><strong>{pData.attendance?.normal_checked_in || 0} / {pData.attendance?.normal_total || 0}</strong></div>
                </div>
                <div className="progress-container">
                  <span>نسبة الحضور الكلية</span>
                  <div className="progress-bar-wrapper">
                    <div className="progress-bar-fill" style={{ width: `${pData.attendance?.attendance_rate || 0}%`, background: '#60a5fa' }} />
                  </div>
                  <strong>{pData.attendance?.attendance_rate || 0}%</strong>
                </div>
              </div>
            </div>

            <div className="analytics-funnel-grid">
              <section className="dashboard-section">
                <h3>اتجاه الحفلات آخر 6 أشهر</h3>
                <div className="month-trend">
                  {(pData.monthly_trend || []).map((month: any) => {
                    const maxOps = Math.max(1, ...(pData.monthly_trend || []).map((m: any) => Number(m.operations || 0)))
                    const height = Math.max(8, Math.round((Number(month.operations || 0) * 100) / maxOps))
                    return <article key={month.month}>
                      <div className="month-bar"><i style={{ height: `${height}%` }} /></div>
                      <strong>{month.operations}</strong>
                      <span>{month.month}</span>
                      <small>{month.guest_capacity} ضيف</small>
                    </article>
                  })}
                  {!(pData.monthly_trend || []).length && <div className="booking-empty">لا توجد بيانات شهرية بعد.</div>}
                </div>
              </section>

              <section className="dashboard-section">
                <h3>جودة المسح والتحضير</h3>
                <div className="scan-quality-grid">
                  <article><span>مقبولة</span><strong>{scanQuality.success_scans || 0}</strong></article>
                  <article><span>مكررة</span><strong>{scanQuality.duplicate_scans || 0}</strong></article>
                  <article><span>مرفوضة</span><strong>{scanQuality.rejected_scans || 0}</strong></article>
                  <article><span>نسبة النجاح</span><strong>{scanQuality.scan_success_rate || 0}%</strong></article>
                </div>
                <div className="progress-container">
                  <span>مؤشر دقة المسح</span>
                  <div className="progress-bar-wrapper">
                    <div className="progress-bar-fill" style={{ width: `${scanQuality.scan_success_rate || 0}%`, background: '#22c55e' }} />
                  </div>
                </div>
              </section>
            </div>

            {/* Upcoming Events & Gate Traffic */}
            <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 20 }}>
              {/* Upcoming Events */}
              <div className="dashboard-section">
                <h3>جدول الحفلات القادمة ({pData.upcoming_events?.length || 0})</h3>
                <div className="upcoming-events-grid">
                  {pData.upcoming_events?.map((ev: any) => (
                    <div className="upcoming-event-card" key={ev.event_id}>
                      <div className="upcoming-event-card__title">{ev.title}</div>
                      <div className="upcoming-event-card__meta">
                        <span><Building2 style={{ width: 14, display: 'inline', marginInlineEnd: 4 }} />{ev.client_name}</span>
                        <span><CalendarDays style={{ width: 14, display: 'inline', marginInlineEnd: 4 }} />{new Date(ev.start_date).toLocaleString('ar')}</span>
                      </div>
                      <div className="progress-bar-wrapper" style={{ height: 6 }}>
                        <div className="progress-bar-fill" style={{ width: `${ev.progress || 0}%` }} />
                      </div>
                      <div className="upcoming-event-card__stats">
                        <div><span>التذاكر</span><strong>{ev.invitation_count}</strong></div>
                        <div><span>البوابات</span><strong>{ev.gate_count}</strong></div>
                      </div>
                      <Link to={`/team-events/${ev.operation_id}`} className="btn-primary" style={{ textAlign: 'center', display: 'block', textDecoration: 'none', padding: 8, fontSize: 13, borderRadius: 8 }}>
                        إدارة الحفل
                      </Link>
                    </div>
                  ))}
                  {!pData.upcoming_events?.length && <div className="booking-empty" style={{ gridColumn: '1 / -1' }}>لا توجد حفلات نشطة مجدولة قريباً.</div>}
                </div>
              </div>

              {/* Gate Distribution */}
              <div className="dashboard-section">
                <h3>توزيع الحضور على البوابات</h3>
                <div className="gate-flow-list">
                  {pData.gates?.map((gate: any) => {
                    const totalCheckins = pData.attendance?.checked_in_count || 1
                    const percentage = Math.round((gate.checkins * 100) / totalCheckins)
                    return (
                      <div className="gate-flow-item" key={gate.gate_id}>
                        <div className="gate-flow-item__info">
                          <strong>{gate.gate_name}</strong>
                          <span style={{ fontSize: 11, color: '#94a3b8' }}>{gate.event_title}</span>
                          <strong>{gate.checkins} مسح ({percentage}%)</strong>
                        </div>
                        <div className="gate-flow-item__bar">
                          <div className="gate-flow-item__fill" style={{ width: `${percentage || 1}%` }} />
                        </div>
                      </div>
                    )
                  })}
                  {!pData.gates?.length && <div className="booking-empty">لا توجد بوابات نشطة حالياً.</div>}
                </div>
              </div>
            </div>

            {/* Performance KPIs and Timeline */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
              {/* Performers */}
              <div className="dashboard-section">
                <h3>مؤشرات أداء موظفي الفريق</h3>
                <div className="top-performers-list">
                  {pData.top_performers?.map((performer: any, idx: number) => {
                    const rate = performer.completed_tasks > 0 
                      ? Math.round((performer.on_time_tasks * 100) / performer.completed_tasks)
                      : 0
                    return (
                      <div className="performer-item" key={idx}>
                        <div className="performer-info">
                          <div className="performer-avatar">{(performer.full_name || 'ع').charAt(0)}</div>
                          <div>
                            <strong>{performer.full_name}</strong>
                            <div style={{ fontSize: 12, color: '#94a3b8' }}>تم تسليم {performer.completed_tasks} مهمة مكتملة</div>
                          </div>
                        </div>
                        <div style={{ textAlign: 'left' }}>
                          <span style={{ fontSize: 12, color: '#10b981', fontWeight: 600 }}>معدل الالتزام بالمواعيد</span>
                          <strong style={{ display: 'block', fontSize: 16 }}>{rate}%</strong>
                        </div>
                      </div>
                    )
                  })}
                  {!pData.top_performers?.length && <div className="booking-empty">لا توجد بيانات مهام مكتملة للموظفين حالياً.</div>}
                </div>
              </div>

              {/* Activity Feed */}
              <div className="dashboard-section">
                <h3>آخر الأنشطة والعمليات الجارية</h3>
                <div className="operation-timeline" style={{ maxHeight: 400, overflowY: 'auto', paddingInlineStart: 8 }}>
                  {pData.recent_activity?.map((act: any, idx: number) => (
                    <article key={idx} style={{ marginBottom: 16 }}>
                      <CheckCircle2 style={{ color: '#c9a96e', width: 18, height: 18 }} />
                      <div>
                        <strong>{act.actor_name || 'النظام'}</strong>: {act.action}
                        <span style={{ fontSize: 11, color: '#94a3b8', display: 'block', marginTop: 4 }}>
                          {new Date(act.created_at).toLocaleString('ar')}
                        </span>
                      </div>
                    </article>
                  ))}
                  {!pData.recent_activity?.length && <div className="booking-empty">لا توجد سجلات نشاط مسجلة.</div>}
                </div>
              </div>
            </div>
          
      </div>
    )}

    {providerTab === 'calendar' && <section className="team-calendar-workspace">
      <header className="team-calendar-workspace__head">
        <div><span>تخطيط الحفلات</span><h2>تقويم الفريق</h2><p>راجع السعة التشغيلية قبل قبول الطلبات أو توزيع فريقك على أي حفل.</p></div>
        <div className="team-calendar-workspace__summary"><span>الموعد المحدد</span><strong>{selectedDayConfirmed.length ? `${selectedDayConfirmed.length} حفل مجدول` : 'اليوم متاح'}</strong></div>
      </header>
      <div className="team-calendar-layout">
        <section className="team-calendar" aria-label="تقويم عمليات الفريق">
          <header className="team-calendar__toolbar">
            <div className="team-calendar__controls"><button type="button" onClick={() => setCalendarCursor(value => new Date(value.getFullYear(), value.getMonth() - 1, 1))} aria-label="الشهر السابق"><ChevronRight size={18} /></button><button type="button" className="team-calendar__today" onClick={() => { const today = new Date(); setCalendarCursor(new Date(today.getFullYear(), today.getMonth(), 1)); setSelectedCalendarDay(calendarDateKey(today)) }}>اليوم</button><button type="button" onClick={() => setCalendarCursor(value => new Date(value.getFullYear(), value.getMonth() + 1, 1))} aria-label="الشهر التالي"><ChevronLeft size={18} /></button></div>
            <label className="team-calendar__date-search"><Search size={14} /><span>ابحث بتاريخ</span><input type="date" value={selectedCalendarDay} onChange={event => { const value = event.target.value; if (!value) return; const date = new Date(`${value}T12:00:00`); setSelectedCalendarDay(value); setCalendarCursor(new Date(date.getFullYear(), date.getMonth(), 1)) }} /></label>
            <h3>{calendarMonthLabel}</h3>
            <div className="team-calendar__legend"><span><i className="team-calendar__legend-operation" />حفل مجدول</span><span><i className="team-calendar__legend-request" />طلب بانتظار القرار</span></div>
          </header>
          <div className="team-calendar__weekdays">{['الأحد', 'الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت'].map(day => <span key={day}>{day}</span>)}</div>
          <div className="team-calendar__grid">{calendarMonthCells.map(day => {
            const scheduled = day.entries.filter(entry => entry.kind === 'operation' && !['completed', 'cancelled'].includes(entry.status))
            return <button type="button" key={day.key} className={`team-calendar__day${day.inCurrentMonth ? '' : ' team-calendar__day--outside'}${day.key === selectedCalendarDay ? ' team-calendar__day--selected' : ''}${scheduled.length ? ' team-calendar__day--busy' : ''}`} onClick={() => setSelectedCalendarDay(day.key)}>
              <span className="team-calendar__date"><time dateTime={day.key}>{day.date.getDate()}</time>{scheduled.length ? <b>{scheduled.length}</b> : null}</span>
              <div className="team-calendar__items">{day.entries.slice(0, 2).map(entry => <span key={entry.id} className={`team-calendar__item team-calendar__item--${entry.kind}`}>{entry.title}</span>)}{day.entries.length > 2 && <small>+{day.entries.length - 2} أخرى</small>}</div>
            </button>
          })}</div>
        </section>
        <aside className="team-calendar-day-panel">
          <div className="team-calendar-day-panel__head"><span>تفاصيل اليوم</span><h3>{new Date(`${selectedCalendarDay}T12:00:00`).toLocaleDateString('ar-SA-u-ca-gregory', { weekday: 'long', day: 'numeric', month: 'long' })}</h3><p className={selectedDayConfirmed.length ? 'team-calendar-day-panel__busy' : 'team-calendar-day-panel__free'}>{selectedDayConfirmed.length ? `لديك ${selectedDayConfirmed.length} حفل مجدول في هذا اليوم` : 'لا توجد حفلات مجدولة — اليوم متاح'}</p></div>
          <div className="team-calendar-day-panel__entries">{selectedDayEntries.length ? selectedDayEntries.map(entry => <button type="button" key={entry.id} className="team-calendar-day-panel__entry" onClick={() => {
            if (entry.kind === 'operation') setSelectedOperation((operations.data || []).find(operation => operation.id === entry.operationId) || null)
            else setSelectedInboxBooking((inbox.data || []).find(booking => booking.id === entry.bookingId) || null)
          }}><span className={`team-calendar-day-panel__dot team-calendar-day-panel__dot--${entry.kind}`} /><div><strong>{entry.title}</strong><small>{operationTime(entry.startsAt)} · {entry.detail}</small></div><em>{entry.kind === 'operation' ? operationStatusLabels[entry.status] || entry.status : 'طلب وارد'}</em></button>) : <div className="team-calendar-day-panel__empty"><CalendarDays size={22} /><strong>لا توجد حجوزات في هذا اليوم</strong><span>يمكن للفريق استيعاب حفل جديد حسب السعة والأعضاء المتاحين.</span></div>}</div>
        </aside>
      </div>
      {selectedOperation && <OperationPreviewModal operation={selectedOperation} close={() => setSelectedOperation(null)} start={operation => { if (operation.booking_id) start.mutate(operation.booking_id) }} complete={operation => { if (operation.booking_id) setCompleteTarget({ id: operation.booking_id, title: operation.title }) }} canComplete={canManageBookings} />}
      {selectedInboxBooking && <BookingRequestDrawer booking={selectedInboxBooking} close={() => setSelectedInboxBooking(null)} canRespond={canRespondBookings} canComplete={canManageBookings} respond={(booking, action) => { setRespondNote(''); setRespondState({ booking, action }) }} start={booking => start.mutate(booking.id)} complete={booking => setCompleteTarget({ id: booking.id, title: booking.title })} />}
    </section>}

    {providerTab === 'groups' && (
      <section className="team-groups-workspace">
        <header className="team-groups-workspace__head">
          <div><span>تنظيم الموارد</span><h2>المجموعات التشغيلية</h2><p>كوّن فرقاً ثابتة بحسب التخصص أو الوردية، ثم أسندها مباشرة إلى عمليات الحفلات.</p></div>
          <button onClick={() => setGroupDialog(true)}><Plus size={17} />إنشاء مجموعة</button>
        </header>

        {!groups.data?.length ? <section className="team-groups-empty">
          <div className="team-groups-empty__icon"><Users size={26} /></div>
          <div><span>ابدأ بتنظيم فريقك</span><h3>لا توجد مجموعات تشغيلية حتى الآن</h3><p>أنشئ مجموعة مثل «الاستقبال» أو «الدخول والمسح»، ثم أضف أعضاء الفريق إليها لتوزيعهم بسرعة على الحفلات.</p></div>
          <button onClick={() => setGroupDialog(true)}><Plus size={17} />إنشاء أول مجموعة</button>
        </section> : <div className="team-groups-grid">
          {groups.data.map(group => <article className="team-group-card" key={group.id} style={{ '--group-color': group.color } as React.CSSProperties}>
            <header><div className="team-group-card__marker"><Users size={18} /></div><div><h3>{group.name}</h3><span>{group.members_count} أعضاء في المجموعة</span></div></header>
            <div className="team-group-card__summary"><span><Users size={15} />الأعضاء</span><strong>{group.members_count}</strong><span><ListChecks size={15} />الإسنادات</span><strong>{group.assignments?.length || 0}</strong></div>
            <div className="team-group-card__assignments">
              <div className="team-group-card__assignments-head"><span>الحفلات المسندة</span><small>{group.assignments?.length ? 'يتلقى الأعضاء إشعاراً عند الإسناد' : 'لم تُسند المجموعة إلى حفل بعد'}</small></div>
              {group.assignments?.length ? group.assignments.slice(0, 3).map(assignment => <div className="team-group-card__assignment" key={assignment.operation_id}>
                <div><strong>{assignment.title}</strong><small>أُسندت في {new Date(assignment.assigned_at).toLocaleDateString('ar')}</small></div>
                <span className={`operation-status operation-status--${assignment.status}`}>{operationStatusLabels[assignment.status] || assignment.status}</span>
              </div>) : <div className="team-group-card__assignment team-group-card__assignment--empty">لا يوجد إسناد نشط لهذه المجموعة.</div>}
              {(group.assignments?.length || 0) > 3 && <small className="team-group-card__more">+ {group.assignments.length - 3} إسنادات أخرى</small>}
            </div>
            <div className="team-group-card__actions">
              <label><span>إضافة عضو</span><select defaultValue="" onChange={async event => {
                if (!event.target.value) return
                try { await bookingsAPI.addGroupMember(group.id, event.target.value); toast.success('تمت إضافة العضو'); qc.invalidateQueries({ queryKey: ['booking-groups'] }) }
                catch (error: any) { toast.apiError('تعذرت إضافة العضو', error) }
                event.target.value = ''
              }}><option value="">اختر عضوًا...</option>{members.data?.filter(member => member.status === 'active').map(member => <option key={member.user_id} value={member.user_id}>{member.full_name || member.email || member.user_id}</option>)}</select></label>
              <label><span>إسناد إلى حفل</span><select defaultValue="" disabled={!assignableOperations.length} onChange={async event => {
                if (!event.target.value) return
                try {
                  await bookingsAPI.assignOperation(group.id, event.target.value)
                  toast.success('تم إسناد المجموعة للحفل وإشعار أعضائها')
                  qc.invalidateQueries({ queryKey: ['booking-groups'] })
                  qc.invalidateQueries({ queryKey: ['operations'] })
                  qc.invalidateQueries({ queryKey: ['provider-dashboard'] })
                } catch (error: any) { toast.apiError('تعذر الإسناد', error) }
                event.target.value = ''
              }}><option value="">{assignableOperations.length ? 'اختر الحفل...' : 'لا توجد حفلات قابلة للإسناد'}</option>{assignableOperations.map(operation => <option key={operation.id} value={operation.id}>{operation.title}</option>)}</select></label>
            </div>
          </article>)}
        </div>}

        <section className="team-groups-workspace__hint"><Users size={20} /><div><strong>إدارة أعضاء الفريق</strong><p>أضف حسابات الموظفين وحدد صلاحياتهم من شاشة الأعضاء، ثم أضفهم إلى مجموعات التشغيل هنا.</p></div><a href="/users">إدارة أعضاء الفريق</a></section>
      </section>
    )}

    {providerTab === 'requests' && <section className="booking-requests-workspace">
      <div className="booking-tabs-title"><div><span>مركز الطلبات</span><h2>الطلبات الواردة للمنظم</h2></div><b>{inbox.data?.length || 0} طلب</b></div>
      {inbox.data?.length ? <div className="booking-request-table-wrap">
        <table className="booking-request-table">
          <thead><tr><th>الحفل</th><th>المؤسسة</th><th>الموعد</th><th>الضيوف</th><th>الحالة</th><th aria-label="التفاصيل" /></tr></thead>
          <tbody>{inbox.data.map(booking => <tr key={booking.id} tabIndex={0} onClick={() => setSelectedInboxBooking(booking)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') setSelectedInboxBooking(booking) }}>
            <td><div className="booking-request-table__event"><span><CalendarDays size={15} /></span><div><strong>{booking.title}</strong><small>{booking.event_type || 'فعالية'}</small></div></div></td>
            <td><strong>{booking.requester_name}</strong></td>
            <td><time dateTime={booking.starts_at}>{new Date(booking.starts_at).toLocaleDateString('ar')}<small>{new Date(booking.starts_at).toLocaleTimeString('ar', { hour: 'numeric', minute: '2-digit' })}</small></time></td>
            <td>{booking.guest_count} ضيف</td>
            <td><span className={`booking-status status-${booking.status}`}>{statusLabels[booking.status]}</span></td>
            <td><button type="button" onClick={event => { event.stopPropagation(); setSelectedInboxBooking(booking) }}>التفاصيل <ChevronLeft size={15} /></button></td>
          </tr>)}</tbody>
        </table>
      </div> : <div className="booking-empty">لا توجد طلبات حجز واردة حالياً.</div>}
      {selectedInboxBooking && <BookingRequestDrawer booking={selectedInboxBooking} close={() => setSelectedInboxBooking(null)} canRespond={canRespondBookings} canComplete={canManageBookings} respond={(booking, action) => { setRespondNote(''); setRespondState({ booking, action }) }} start={booking => start.mutate(booking.id)} complete={booking => setCompleteTarget({ id: booking.id, title: booking.title })} />}
    </section>}

    {providerTab === 'events' && <>
      <section className="operations-page">
        <div className="operations-page__head">
          <div>
            <span className="operations-page__eyebrow">مساحة التنفيذ</span>
            <h2>الحفلات والمشاريع</h2>
            <p>كل ما يعمل عليه فريقك، من التخطيط حتى إغلاق الحفل.</p>
          </div>
          <div className="operations-page__count"><strong>{filteredEvents.length}</strong><span>حفل ومشروع</span></div>
        </div>

        <div className="operations-toolbar">
          <div className="operations-search">
            <Search />
          <input
            type="text"
            placeholder="ابحث عن اسم الحفل، أو العميل، أو الموقع..."
            value={eventSearch}
            onChange={e => setEventSearch(e.target.value)}
          />
          </div>
          <div className="operations-toolbar__filters">
            <select aria-label="تصفية حسب التاريخ" value={eventDateFilter} onChange={e => setEventDateFilter(e.target.value as typeof eventDateFilter)}>
              <option value="all">كل التواريخ</option>
              <option value="today">اليوم</option>
              <option value="week">هذا الأسبوع</option>
              <option value="upcoming">الحفلات القادمة</option>
            </select>
            <select aria-label="تصفية حسب الحالة" value={eventStatusFilter} onChange={e => setEventStatusFilter(e.target.value as typeof eventStatusFilter)}>
              <option value="all">كل الحالات</option>
              <option value="active">الحفلات النشطة</option>
              <option value="completed">المكتملة</option>
              <option value="cancelled">الملغية</option>
            </select>
          </div>
        </div>

        {filteredEvents.length ? <div className="booking-request-table-wrap operations-table-wrap">
          <table className="booking-request-table operations-table">
            <thead><tr><th>الحفل</th><th>المؤسسة</th><th>الموعد</th><th>الدعوات</th><th>التقدم</th><th>الحالة</th><th aria-label="التفاصيل" /></tr></thead>
            <tbody>{filteredEvents.map(op => <tr key={op.id} tabIndex={0} onClick={() => setSelectedOperation(op)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') setSelectedOperation(op) }}>
              <td><div className="booking-request-table__event"><span><CalendarDays size={15} /></span><div><strong>{op.title}</strong><small>{op.tasks_done} من {op.tasks_count} مهام</small></div></div></td>
              <td><strong>{op.requester_name}</strong></td>
              <td><time dateTime={op.starts_at}>{operationDate(op.starts_at)}<small>{operationTime(op.starts_at)}</small></time></td>
              <td>{op.guest_count} دعوة</td>
              <td><div className="operations-table__progress"><span>{op.progress || 0}%</span><i><b style={{ width: `${op.progress || 0}%` }} /></i></div></td>
              <td><span className={`operation-status operation-status--${op.status}`}>{operationStatusLabels[op.status] || op.status}</span></td>
              <td><button type="button" onClick={event => { event.stopPropagation(); setSelectedOperation(op) }}>التفاصيل <ChevronLeft size={15} /></button></td>
            </tr>)}</tbody>
          </table>
        </div> : <div className="booking-empty">لم يتم العثور على أي حفلات مطابقة للبحث أو الفلترة.</div>}
        {selectedOperation && <OperationPreviewModal operation={selectedOperation} close={() => setSelectedOperation(null)} canComplete={canManageBookings} start={operation => { if (operation.booking_id) start.mutate(operation.booking_id) }} complete={operation => { if (operation.booking_id) setCompleteTarget({ id: operation.booking_id, title: operation.title }) }} />}
      </section>
    </>}

    {['tasks','guests','attendance','files','notifications','reports'].includes(providerTab) && (
      <section className="provider-dashboard-container" style={{ marginTop: 16 }}>
        <div className="analytics-command"><div><small>مساحة التشغيل</small><h2>{({calendar:'التقويم',tasks:'المهام',guests:'الضيوف والدعوات',attendance:'الحضور والبوابات',files:'الملفات',notifications:'الإشعارات',reports:'التقارير'} as Record<string,string>)[providerTab]}</h2><p>بيانات العمليات المسندة إلى فريقك فقط.</p></div></div>
        {providerTab === 'tasks' && <div className="analytics-kpi-strip"><article><span>إجمالي المهام</span><strong>{pData.tasks?.total_tasks || 0}</strong></article><article><span>المتأخرة</span><strong>{pData.task_alerts?.overdue_tasks || pData.tasks?.overdue_tasks || 0}</strong></article><article><span>بانتظار الاعتماد</span><strong>{pData.task_alerts?.awaiting_approval || 0}</strong></article></div>}
        {providerTab === 'guests' && <div className="analytics-kpi-strip"><article><span>الدعوات</span><strong>{pData.attendance?.total_invitations || 0}</strong></article><article><span>المقبولة</span><strong>{pData.attendance?.accepted_count || 0}</strong></article><article><span>الحضور</span><strong>{pData.attendance?.checked_in_count || 0}</strong></article></div>}
        {providerTab === 'attendance' && <div className="analytics-kpi-strip"><article><span>جودة المسح</span><strong>{pData.scan_quality?.scan_success_rate || 0}%</strong></article><article><span>مسح اليوم</span><strong>{pData.attendance_today?.scans_today || 0}</strong></article><article><span>البوابات</span><strong>{(pData.gates || []).length}</strong></article></div>}
        {providerTab === 'files' && <div className="upcoming-events-grid">{(pData.recent_files || []).map((file: any) => <article className="analytics-card" key={file.attachment_id}><h3>{file.file_name}</h3><p>{file.created_at} · {file.size_bytes} bytes</p></article>)}{!(pData.recent_files || []).length && <div className="booking-empty">لا توجد ملفات حديثة.</div>}</div>}
        {providerTab === 'notifications' && <div className="booking-list">{(pData.critical_notifications || []).map((n: any) => <article className="booking-card" key={n.id}><h3>{n.title}</h3><p>{n.message}</p><small>{n.created_at}</small></article>)}{!(pData.critical_notifications || []).length && <div className="booking-empty">لا توجد تنبيهات حرجة.</div>}</div>}
        {providerTab === 'reports' && <div className="analytics-kpi-strip"><article><span>العمليات النشطة</span><strong>{pData.operations?.active_operations || 0}</strong></article><article><span>متوسط زمن الرد</span><strong>{pData.booking_funnel?.avg_response_hours || 0} ساعة</strong></article><article><span>استخدام الباقة</span><strong>{pData.plan_usage?.plan_code || '—'}</strong></article></div>}
      </section>
    )}

    {respondState && <ConfirmDialog
      isOpen
      title={respondState.action === 'accepted' ? 'تأكيد قبول الطلب' : respondState.action === 'rejected' ? 'تأكيد رفض الطلب' : 'طلب معلومات إضافية'}
      message={respondState.action === 'accepted'
        ? `سيتم قبول طلب حفل «${respondState.booking.title}» وإنشاء مشروع التشغيل تلقائيًا.`
        : 'أدخل ملاحظة تصل إلى المؤسسة (سبب الرفض أو المعلومات المطلوبة).'}
      confirmLabel={respondState.action === 'accepted' ? 'قبول' : respondState.action === 'rejected' ? 'رفض' : 'إرسال'}
      variant={respondState.action === 'rejected' ? 'danger' : respondState.action === 'accepted' ? 'default' : 'warning'}
      isPending={response.isPending}
      onCancel={() => { setRespondState(null); setRespondNote('') }}
      onConfirm={() => response.mutate({ id: respondState.booking.id, action: respondState.action, note: respondState.action === 'accepted' ? undefined : (respondNote.trim() || undefined) })}
    >
      {respondState.action !== 'accepted' && <textarea className="confirm-dialog__textarea" placeholder={respondState.action === 'rejected' ? 'سبب الرفض...' : 'المعلومات المطلوبة...'} value={respondNote} onChange={e => setRespondNote(e.target.value)} />}
    </ConfirmDialog>}

    {completeTarget && <ConfirmDialog
      isOpen
      title="تأكيد إكمال الحفل"
      message={`سيتم تعليم حفل «${completeTarget.title}» كمكتمل. لا يمكن التراجع عن هذه العملية.`}
      confirmLabel="إكمال الحفل"
      variant="default"
      isPending={complete.isPending}
      onCancel={() => setCompleteTarget(null)}
      onConfirm={() => complete.mutate(completeTarget.id)}
    />}

    {groupDialog && <ConfirmDialog
      isOpen
      title="إضافة مجموعة تشغيلية"
      message="أدخل اسم المجموعة الجديدة."
      confirmLabel="إضافة"
      isPending={createGroup.isPending}
      onCancel={() => { setGroupDialog(false); setGroupName('') }}
      onConfirm={() => groupName.trim() && createGroup.mutate({ name: groupName.trim() })}
    >
      <input className="confirm-dialog__input" placeholder="اسم المجموعة" value={groupName} onChange={e => setGroupName(e.target.value)} autoFocus />
    </ConfirmDialog>}
  </WorkspaceShell>
}
