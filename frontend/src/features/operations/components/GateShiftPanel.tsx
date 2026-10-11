import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarClock, Layers3, Plus, Radio, Smartphone, UserPlus, UsersRound, X } from 'lucide-react'
import { bookingsAPI } from '@features/bookings/api/bookingsApi'
import { toast } from '@components/toast'
import {
  operationsAPI,
  type GateShiftRole,
  type GateShiftStatus,
} from '../api/operationsApi'
import './gate-shifts.css'

type Gate = { id: string; name?: string; name_ar?: string | null; is_active: boolean }

const statusLabel: Record<GateShiftStatus, string> = {
  scheduled: 'مجدولة',
  active: 'فعّالة الآن',
  completed: 'منتهية',
  cancelled: 'ملغاة',
}

const roleLabel: Record<GateShiftRole, string> = {
  scanner: 'مسّاح',
  supervisor: 'مشرف بوابة',
}

const localInput = (date: Date) => {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

const initialShiftForm = () => {
  const start = new Date()
  start.setMinutes(0, 0, 0)
  const end = new Date(start.getTime() + 4 * 60 * 60 * 1000)
  return { gate_id: '', starts_at: localInput(start), ends_at: localInput(end), supervisor_user_id: '' }
}

export function GateShiftPanel({
  eventId,
  operationId,
  gates,
  canManage,
}: {
  eventId: string
  operationId: string
  gates: Gate[]
  canManage: boolean
}) {
  const qc = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [selectedShiftId, setSelectedShiftId] = useState<string | null>(null)
  const [form, setForm] = useState(initialShiftForm)
  const [assignMode, setAssignMode] = useState<'member' | 'group' | null>(null)
  const [assignId, setAssignId] = useState('')
  const [assignRole, setAssignRole] = useState<GateShiftRole>('scanner')

  const shifts = useQuery({
    queryKey: ['gate-shifts', eventId],
    queryFn: () => operationsAPI.gateShifts(eventId),
    enabled: Boolean(eventId),
  })
  const operation = useQuery({
    queryKey: ['operation', operationId],
    queryFn: () => operationsAPI.detail(operationId),
    enabled: Boolean(operationId) && (createOpen || Boolean(selectedShiftId)),
  })
  const groups = useQuery({
    queryKey: ['booking-groups'],
    queryFn: bookingsAPI.groups,
    enabled: Boolean(selectedShiftId),
  })
  const detail = useQuery({
    queryKey: ['gate-shift', selectedShiftId],
    queryFn: () => operationsAPI.gateShift(selectedShiftId!),
    enabled: Boolean(selectedShiftId),
  })
  const deviceSessions = useQuery({
    queryKey: ['gate-shift-devices', selectedShiftId],
    queryFn: () => operationsAPI.gateShiftDeviceSessions(selectedShiftId!),
    enabled: Boolean(selectedShiftId),
    refetchInterval: detail.data?.shift.status === 'active' ? 15_000 : false,
  })

  const members = useMemo(() => operation.data?.members ?? [], [operation.data?.members])
  const activeGates = gates.filter((gate) => gate.is_active)
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['gate-shifts', eventId] })
    qc.invalidateQueries({ queryKey: ['gate-shift', selectedShiftId] })
    qc.invalidateQueries({ queryKey: ['gate-shift-devices', selectedShiftId] })
  }

  const createShift = useMutation({
    mutationFn: () => operationsAPI.createGateShift({
      event_id: eventId,
      gate_id: form.gate_id,
      operation_id: operationId,
      starts_at: new Date(form.starts_at).toISOString(),
      ends_at: new Date(form.ends_at).toISOString(),
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Riyadh',
      supervisor_user_id: form.supervisor_user_id,
    }),
    onSuccess: (shift) => {
      toast.success('تم إنشاء وردية البوابة')
      setCreateOpen(false)
      setForm(initialShiftForm())
      setSelectedShiftId(shift.id)
      invalidate()
    },
    onError: (error: any) => toast.apiError('تعذر إنشاء الوردية', error),
  })
  const setStatus = useMutation({
    mutationFn: ({ shiftId, status }: { shiftId: string; status: GateShiftStatus }) =>
      operationsAPI.updateGateShift(shiftId, { status }),
    onSuccess: () => { toast.success('تم تحديث حالة الوردية'); invalidate() },
    onError: (error: any) => toast.apiError('تعذر تحديث الوردية', error),
  })
  const assign = useMutation({
    mutationFn: () => {
      if (!selectedShiftId || !assignId || !assignMode) throw new Error('missing assignment data')
      return assignMode === 'member'
        ? operationsAPI.assignGateShiftMember(selectedShiftId, { user_id: assignId, role: assignRole })
        : operationsAPI.assignGateShiftGroup(selectedShiftId, { group_id: assignId, role: assignRole })
    },
    onSuccess: () => {
      toast.success(assignMode === 'member' ? 'تم إسناد العضو للوردية' : 'تم أخذ لقطة المجموعة وإسنادها')
      setAssignMode(null); setAssignId(''); setAssignRole('scanner'); invalidate()
    },
    onError: (error: any) => toast.apiError('تعذر حفظ الإسناد', error),
  })
  const revoke = useMutation({
    mutationFn: (sessionId: string) => operationsAPI.revokeGateShiftDeviceSession(selectedShiftId!, sessionId),
    onSuccess: () => { toast.success('تم إلغاء جلسة الجهاز'); invalidate() },
    onError: (error: any) => toast.apiError('تعذر إلغاء جلسة الجهاز', error),
  })

  if (shifts.isLoading) return <div className="gate-shift-empty">جاري تحميل ورديات البوابات…</div>

  return (
    <section className="gate-shifts" aria-label="ورديات البوابات">
      <header className="gate-shifts__header">
        <div>
          <span>تشغيل ميداني مضبوط</span>
          <h3>ورديات البوابات</h3>
          <p>لا يبدأ المسح إلا لعضو مكلّف في وردية فعّالة وعلى جهاز مسجل.</p>
        </div>
        {canManage && <button className="gate-shift-primary" onClick={() => setCreateOpen(true)}><Plus size={16} /> وردية جديدة</button>}
      </header>

      {!shifts.data?.length ? (
        <div className="gate-shift-empty"><CalendarClock size={22} /><strong>لا توجد ورديات بعد</strong><span>أنشئ وردية وحدد البوابة والمشرف قبل موعد الحفل.</span></div>
      ) : (
        <div className="gate-shift-list">
          {shifts.data.map((shift) => (
            <button className="gate-shift-row" key={shift.id} onClick={() => setSelectedShiftId(shift.id)}>
              <span className={`gate-shift-status gate-shift-status--${shift.status}`}>{statusLabel[shift.status]}</span>
              <div className="gate-shift-row__main"><strong>{shift.gate_name_ar || shift.gate_name || 'بوابة'}</strong><small>{new Date(shift.starts_at).toLocaleString('ar')} — {new Date(shift.ends_at).toLocaleTimeString('ar')}</small></div>
              <div><span>المشرف</span><b>{shift.supervisor_name || 'غير محدد'}</b></div>
              <div><span>الفريق</span><b>{shift.scanners || 0} مسّاح · {shift.supervisors || 0} مشرف</b></div>
              <span className="gate-shift-row__open">التفاصيل</span>
            </button>
          ))}
        </div>
      )}

      {createOpen && (
        <Modal title="إنشاء وردية بوابة" onClose={() => setCreateOpen(false)}>
          <div className="gate-shift-form">
            <label>البوابة<select value={form.gate_id} onChange={(event) => setForm({ ...form, gate_id: event.target.value })}><option value="">اختر بوابة فعّالة</option>{activeGates.map((gate) => <option key={gate.id} value={gate.id}>{gate.name_ar || gate.name}</option>)}</select></label>
            <label>مشرف الوردية<select value={form.supervisor_user_id} onChange={(event) => setForm({ ...form, supervisor_user_id: event.target.value })}><option value="">اختر مشرفاً</option>{members.map((member) => <option key={member.user_id} value={member.user_id}>{member.full_name || member.email}</option>)}</select></label>
            <label>تبدأ في<input type="datetime-local" value={form.starts_at} onChange={(event) => setForm({ ...form, starts_at: event.target.value })} /></label>
            <label>تنتهي في<input type="datetime-local" value={form.ends_at} onChange={(event) => setForm({ ...form, ends_at: event.target.value })} /></label>
          </div>
          <p className="gate-shift-hint">سيُضاف مشرف الوردية تلقائياً إلى فريقها. يجب أن يكون أعضاء المسح مكلّفين بعملية الحفل أولاً.</p>
          <div className="gate-shift-actions"><button className="gate-shift-secondary" onClick={() => setCreateOpen(false)}>إلغاء</button><button className="gate-shift-primary" disabled={!form.gate_id || !form.supervisor_user_id || createShift.isPending} onClick={() => createShift.mutate()}>{createShift.isPending ? 'جارٍ الحفظ…' : 'إنشاء الوردية'}</button></div>
        </Modal>
      )}

      {selectedShiftId && detail.data && (
        <Modal title={`وردية ${detail.data.shift.gate_name_ar || detail.data.shift.gate_name || 'البوابة'}`} onClose={() => { setSelectedShiftId(null); setAssignMode(null) }} wide>
          <div className="gate-shift-detail-top"><div><span className={`gate-shift-status gate-shift-status--${detail.data.shift.status}`}>{statusLabel[detail.data.shift.status]}</span><p>{new Date(detail.data.shift.starts_at).toLocaleString('ar')} — {new Date(detail.data.shift.ends_at).toLocaleString('ar')}</p></div>{canManage && detail.data.shift.status === 'scheduled' && <button className="gate-shift-primary" disabled={setStatus.isPending} onClick={() => setStatus.mutate({ shiftId: selectedShiftId, status: 'active' })}><Radio size={16} /> تفعيل الوردية</button>}</div>
          <div className="gate-shift-detail-grid">
            <article><header><UsersRound size={17} /><strong>أعضاء الوردية</strong>{canManage && <button onClick={() => setAssignMode('member')}><UserPlus size={15} /> إسناد عضو</button>}</header>{detail.data.members.length ? <div className="gate-shift-assignment-list">{detail.data.members.filter((member) => member.is_active).map((member) => <div key={member.user_id}><span>{member.full_name || 'عضو فريق'}</span><small>{roleLabel[member.role]} · {member.assignment_source === 'direct' ? 'مباشر' : 'من لقطة مجموعة'}</small></div>)}</div> : <Empty text="لم يُسند أي عضو بعد" />}</article>
            <article><header><Layers3 size={17} /><strong>مجموعات ملتقطة</strong>{canManage && <button onClick={() => setAssignMode('group')}><Plus size={15} /> إسناد مجموعة</button>}</header>{detail.data.groups.length ? <div className="gate-shift-assignment-list">{detail.data.groups.map((group) => <div key={group.group_id}><span>{group.name}</span><small>{group.snapshotted_members} عضو · {roleLabel[group.role]}</small></div>)}</div> : <Empty text="لا توجد مجموعة مسندة" />}</article>
          </div>
          <article className="gate-shift-devices"><header><Smartphone size={17} /><strong>جلسات الأجهزة</strong></header>{deviceSessions.data?.length ? <div className="gate-shift-device-list">{deviceSessions.data.map((session) => <div key={session.id}><span><b>{session.device_name || session.platform || 'جهاز ميداني'}</b><small>آخر نشاط: {new Date(session.last_seen_at).toLocaleTimeString('ar')}</small></span><em className={`gate-shift-device-status gate-shift-device-status--${session.status}`}>{session.status === 'active' ? 'نشطة' : session.status === 'revoked' ? 'ملغاة' : 'مغلقة'}</em>{canManage && session.status === 'active' && <button className="gate-shift-danger" disabled={revoke.isPending} onClick={() => revoke.mutate(session.id)}>إلغاء</button>}</div>)}</div> : <Empty text="لا توجد جلسات أجهزة مسجلة" />}</article>
          {assignMode && <div className="gate-shift-inline-form"><strong>{assignMode === 'member' ? 'إسناد عضو' : 'إسناد مجموعة مع لقطة ثابتة'}</strong><select value={assignId} onChange={(event) => setAssignId(event.target.value)}><option value="">{assignMode === 'member' ? 'اختر عضواً من فريق الحفل' : 'اختر مجموعة تشغيلية'}</option>{assignMode === 'member' ? members.map((member) => <option key={member.user_id} value={member.user_id}>{member.full_name || member.email}</option>) : groups.data?.map((group) => <option key={group.id} value={group.id}>{group.name} ({group.members_count})</option>)}</select><select value={assignRole} onChange={(event) => setAssignRole(event.target.value as GateShiftRole)}><option value="scanner">مسّاح</option><option value="supervisor">مشرف بوابة</option></select><button className="gate-shift-primary" disabled={!assignId || assign.isPending} onClick={() => assign.mutate()}>{assign.isPending ? 'جارٍ الإسناد…' : 'تأكيد الإسناد'}</button><button className="gate-shift-secondary" onClick={() => setAssignMode(null)}>إلغاء</button></div>}
        </Modal>
      )}
    </section>
  )
}

function Empty({ text }: { text: string }) { return <p className="gate-shift-empty-small">{text}</p> }

function Modal({ title, children, onClose, wide = false }: { title: string; children: React.ReactNode; onClose: () => void; wide?: boolean }) {
  return <div className="gate-shift-modal-backdrop" role="presentation" onMouseDown={onClose}><section className={`gate-shift-modal ${wide ? 'gate-shift-modal--wide' : ''}`} role="dialog" aria-modal="true" aria-label={title} onMouseDown={(event) => event.stopPropagation()}><header><div><span>إدارة ميدانية</span><h2>{title}</h2></div><button aria-label="إغلاق" onClick={onClose}><X /></button></header>{children}</section></div>
}
