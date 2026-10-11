import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Clock, DoorOpen, Edit3, Plus, TrendingUp, UserCheck, Users, X, XCircle } from 'lucide-react'
import { operationsAPI } from '../api/operationsApi'
import { eventsAPI } from '@features/events/api/eventsApi'
import { ConfirmDialog } from '@components/ConfirmDialog'
import { toast } from '@components/toast'
import { GateShiftPanel } from './GateShiftPanel'
import './event-insights.css'

const rsvpLabels: Record<string, string> = {
  confirmed: 'مؤكد',
  declined: 'معتذر',
  pending: 'بانتظار الرد',
}

const resultTone: Record<string, string> = {
  success: 'scan-accepted', accepted: 'scan-accepted',
  rejected: 'scan-rejected', duplicate: 'scan-duplicate',
}

const resultLabel = (result?: string) => {
  if (result === 'success' || result === 'accepted') return 'مقبول'
  if (result === 'rejected') return 'مرفوض'
  if (result === 'duplicate') return 'مكرر'
  return result || '—'
}

type TicketClass = 'normal' | 'vip'
type GateDialog = { id?: string; name: string; name_ar: string; allowed_classes: TicketClass[] }

export function EventInsightsPanel({ operationId, active }: { operationId: string; active: string }) {
  const queryClient = useQueryClient()
  const [gateDialog, setGateDialog] = useState<GateDialog | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null)

  const query = useQuery({
    queryKey: ['operation-insights', operationId, active],
    queryFn: () => operationsAPI.eventInsights(operationId, active as 'guests' | 'gates' | 'live'),
    enabled: Boolean(operationId),
    refetchInterval: active === 'live' ? 15_000 : false,
  })

  const saveGate = useMutation({
    mutationFn: (gate: GateDialog) => {
      const payload = {
        name: gate.name.trim(),
        name_ar: gate.name_ar.trim() || undefined,
        allowed_classes: gate.allowed_classes,
      }
      return gate.id
        ? eventsAPI.updateGate(query.data!.event_id, gate.id, payload)
        : eventsAPI.createGate(query.data!.event_id, payload)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['operation-insights', operationId] })
      queryClient.invalidateQueries({ queryKey: ['gate-shifts', query.data?.event_id] })
      toast.success('تم حفظ البوابة. أضف ورديتها وأعضاءها من قسم الورديات أدناه.')
      setGateDialog(null)
    },
    onError: (error: any) => toast.apiError('تعذر حفظ البوابة', error),
  })
  const deleteGate = useMutation({
    mutationFn: (gateId: string) => eventsAPI.deleteGate(query.data!.event_id, gateId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['operation-insights', operationId] })
      queryClient.invalidateQueries({ queryKey: ['gate-shifts', query.data?.event_id] })
      toast.success('تم حذف البوابة')
      setDeleteTarget(null)
    },
    onError: (error: any) => toast.apiError('تعذر حذف البوابة', error),
  })

  if (query.isLoading) return <div className="operation-empty">جارٍ تحميل بيانات الحفل…</div>
  if (query.isError || !query.data) return <div className="operation-empty">تعذر تحميل بيانات الحفل لهذا المشروع.</div>

  const data = query.data
  const invitations = data.invitations || {}
  const attendanceRate = invitations.total > 0 ? Math.round(((invitations.checked_in || 0) / invitations.total) * 100) : 0
  const confirmationRate = invitations.total > 0 ? Math.round(((invitations.confirmed || 0) / invitations.total) * 100) : 0
  const canManage = data.my_role === 'manager' || data.my_role === 'lead'

  const toggleClass = (ticketClass: TicketClass) => {
    if (!gateDialog) return
    const allowed = gateDialog.allowed_classes.includes(ticketClass)
      ? gateDialog.allowed_classes.filter((item) => item !== ticketClass)
      : [...gateDialog.allowed_classes, ticketClass]
    setGateDialog({ ...gateDialog, allowed_classes: allowed })
  }

  if (active === 'guests') {
    return (
      <section className="event-insights">
        <div className="insight-stats">
          <Stat icon={<Users size={18} />} label="إجمالي الدعوات" value={invitations.total || 0} tone="primary" />
          <Stat icon={<CheckCircle2 size={18} />} label="مؤكدة" value={invitations.confirmed || 0} tone="success" />
          <Stat icon={<XCircle size={18} />} label="معتذرة" value={invitations.declined || 0} tone="danger" />
          <Stat icon={<Clock size={18} />} label="بانتظار الرد" value={invitations.rsvp_pending || 0} tone="warning" />
          <Stat icon={<UserCheck size={18} />} label="تم حضورهم" value={invitations.checked_in || 0} tone="success" />
          <Stat icon={<TrendingUp size={18} />} label="نسبة الحضور" value={`${attendanceRate}%`} tone="primary" />
        </div>
        <div className="insight-section-head"><h3>قائمة ضيوف الحفل</h3><span>{data.guests.length} ضيف</span></div>
        <div className="guest-table operation-surface">
          {!data.guests.length && <div className="operation-empty">لا توجد دعوات مرتبطة بهذا الحفل بعد.</div>}
          {data.guests.map((guest) => (
            <div className="guest-row" key={guest.id}>
              <div className="guest-row__main"><strong>{guest.full_name_ar || guest.full_name || 'ضيف'}</strong><small>{guest.phone || guest.email || '—'}</small></div>
              <span className={`guest-tag ${guest.ticket_class === 'vip' ? 'guest-tag--vip' : ''}`}>{guest.ticket_class === 'vip' ? 'VIP' : 'عادي'}</span>
              <span className={`guest-rsvp rsvp-${guest.rsvp_status}`}>{rsvpLabels[guest.rsvp_status || 'pending']}</span>
              <span className={`guest-checkin ${guest.checked_in_at ? 'checked' : ''}`}>{guest.checked_in_at ? '✓ حضر' : 'التحضير من تطبيق البوابة'}</span>
            </div>
          ))}
        </div>
      </section>
    )
  }

  if (active === 'gates') {
    return (
      <section className="event-insights">
        <header className="insight-section-head">
          <div><h3>بوابات الدخول</h3><span>تُدار صلاحية المسح من خلال الورديات، وليس من البطاقة مباشرة.</span></div>
          {canManage && <button onClick={() => setGateDialog({ name: '', name_ar: '', allowed_classes: ['normal', 'vip'] })} className="btn-primary"><Plus size={16} /> إضافة بوابة</button>}
        </header>
        <div className="gate-cards">
          {!data.gates.length && <div className="operation-empty">لم تُعرّف بوابات لهذا الحفل بعد.</div>}
          {data.gates.map((gate) => (
            <article className="gate-card" key={gate.id}>
              <div className="gate-card__head"><DoorOpen size={18} /><strong>{gate.name_ar || gate.name || 'بوابة'}</strong></div>
              <div className="gate-card__stat"><span>المسحات المقبولة</span><b>{gate.scans} مسحة</b></div>
              <span className={`gate-status ${gate.is_active ? 'gate-status--on' : 'gate-status--off'}`}>{gate.is_active ? 'مفعّلة' : 'متوقفة'}</span>
              {canManage && <button className="gate-card__edit" onClick={() => setGateDialog({ id: gate.id, name: gate.name || '', name_ar: gate.name_ar || '', allowed_classes: ['normal', 'vip'] })}><Edit3 size={15} /> تعديل</button>}
            </article>
          ))}
        </div>
        <GateShiftPanel eventId={data.event_id} operationId={operationId} gates={data.gates} canManage={canManage} />

        {gateDialog && (
          <div className="booking-overlay" onMouseDown={() => setGateDialog(null)}>
            <section className="booking-dialog" onMouseDown={(event) => event.stopPropagation()}>
              <div className="booking-dialog__head"><h2>{gateDialog.id ? 'تعديل بوابة' : 'إضافة بوابة جديدة'}</h2><button onClick={() => setGateDialog(null)}><X /></button></div>
              <div className="gate-dialog-form">
                <label>اسم البوابة<input value={gateDialog.name} onChange={(event) => setGateDialog({ ...gateDialog, name: event.target.value })} placeholder="مثال: المدخل الرئيسي" /></label>
                <label>الاسم العربي<input value={gateDialog.name_ar} onChange={(event) => setGateDialog({ ...gateDialog, name_ar: event.target.value })} placeholder="اختياري" /></label>
                <fieldset><legend>فئات الدعوات المسموح بها</legend>{(['normal', 'vip'] as TicketClass[]).map((ticketClass) => <label key={ticketClass}><input type="checkbox" checked={gateDialog.allowed_classes.includes(ticketClass)} onChange={() => toggleClass(ticketClass)} /> {ticketClass === 'vip' ? 'VIP' : 'عادي'}</label>)}</fieldset>
              </div>
              <div className="booking-dialog__actions"><button className="btn-secondary" onClick={() => setGateDialog(null)}>إلغاء</button><button className="btn-primary" disabled={!gateDialog.name.trim() || !gateDialog.allowed_classes.length || saveGate.isPending} onClick={() => saveGate.mutate(gateDialog)}>{saveGate.isPending ? 'جارٍ الحفظ…' : 'حفظ البوابة'}</button></div>
              {gateDialog.id && <button className="gate-delete-link" disabled={deleteGate.isPending} onClick={() => setDeleteTarget({ id: gateDialog.id!, name: gateDialog.name_ar || gateDialog.name })}>حذف البوابة</button>}
            </section>
          </div>
        )}
        {deleteTarget && <ConfirmDialog isOpen title="حذف البوابة" message={`هل تريد حذف بوابة «${deleteTarget.name}»؟ لا يمكن حذفها إن كانت مرتبطة بسجل حضور.`} confirmLabel="حذف البوابة" variant="danger" isPending={deleteGate.isPending} onCancel={() => setDeleteTarget(null)} onConfirm={() => deleteGate.mutate(deleteTarget.id)} />}
      </section>
    )
  }

  return (
    <section className="event-insights">
      <div className="insight-stats">
        <Stat icon={<UserCheck size={18} />} label="إجمالي المسحات" value={invitations.total_scans || 0} tone="primary" />
        <Stat icon={<CheckCircle2 size={18} />} label="الحاضرين" value={invitations.checked_in || 0} tone="success" />
        <Stat icon={<TrendingUp size={18} />} label="نسبة التأكيد" value={`${confirmationRate}%`} tone="primary" />
        <Stat icon={<Users size={18} />} label="المرافقون المؤكدون" value={invitations.plus_ones_confirmed || 0} tone="warning" />
      </div>
      <div className="operation-empty operation-live-note"><strong>المتابعة المباشرة</strong><br />المسح والحضور اليدوي متاحان فقط من تطبيق البوابات بعد تفعيل الوردية وجلسة الجهاز.</div>
      <div className="operation-live-grid">
        <article className="dashboard-section"><h3>ترتيب موظفي التحضير</h3><div className="leaderboard">{!data.scan_leaderboard.length && <div className="operation-empty">لا توجد مسحات مقبولة بعد.</div>}{data.scan_leaderboard.map((item, index) => <div className="leaderboard-row" key={`${item.scanner_name}-${index}`}><span className="leaderboard-rank">{index + 1}</span><span className="leaderboard-name">{item.scanner_name || 'موظف ميداني'}</span><span className="leaderboard-count">{item.accepted_scans} مسحة</span></div>)}</div></article>
        <article className="dashboard-section"><h3>سجل التحضير المباشر</h3><div className="scan-feed">{!data.recent_scans.length && <div className="operation-empty">لا توجد مسحات مسجلة حالياً.</div>}{data.recent_scans.map((scan) => <div className={`scan-row ${resultTone[scan.result] || ''}`} key={scan.id}><div className="scan-row__main"><strong>{scan.guest_name_ar || scan.guest_name || 'ضيف'}</strong><small>{scan.ticket_class === 'vip' ? 'VIP' : 'عادي'} · {scan.gate_name || 'بوابة'}</small></div><span className={`scan-result ${resultTone[scan.result]?.replace('scan-', 'scan-result--') || ''}`}>{resultLabel(scan.result)}</span><span className="scan-time">{new Date(scan.created_at).toLocaleTimeString('ar')} · {scan.scanner_name || 'النظام'}</span></div>)}</div></article>
      </div>
    </section>
  )
}

function Stat({ icon, label, value, tone }: { icon: React.ReactNode; label: string; value: number | string; tone: string }) {
  return <div className={`insight-stat insight-stat--${tone}`}><span className="insight-stat__icon">{icon}</span><span className="insight-stat__label">{label}</span><strong className="insight-stat__value">{value}</strong></div>
}
