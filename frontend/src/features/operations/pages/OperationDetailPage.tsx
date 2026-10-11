import { useEffect, useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity,
  CalendarDays,
  CheckCircle2,
  ClipboardList,
  DoorOpen,
  FileUp,
  FileText,
  History,
  LayoutDashboard,
  MapPin,
  Paperclip,
  Phone,
  Plus,
  Radio,
  Users,
  UserPlus,
} from 'lucide-react'
import { WorkspaceShell } from '@features/workspace/components/WorkspaceShell'
import { operationsAPI, type TaskStatus } from '../api/operationsApi'
import { bookingsAPI } from '@features/bookings/api/bookingsApi'
import { usersAPI } from '@features/users/api/usersApi'
import { EventInsightsPanel } from '../components/EventInsightsPanel'
import { ConfirmDialog } from '@components/ConfirmDialog'
import { toast } from '@components/toast'
import { PERM, usePermission } from '@shared/permissions'
import './operation.css'

type OperationTab = 'overview' | 'guests' | 'gates' | 'live' | 'tasks' | 'team' | 'files' | 'activity'

const taskLabels: Record<TaskStatus, string> = {
  todo: 'جديدة',
  in_progress: 'قيد التنفيذ',
  blocked: 'متوقفة',
  done: 'مكتملة',
}

const roleLabels: Record<string, string> = {
  manager: 'مدير الحفل',
  lead: 'قائد مجموعة',
  member: 'عضو تشغيل',
}

const operationStatusLabels: Record<string, string> = {
  planning: 'قيد التخطيط',
  ready: 'جاهز للتنفيذ',
  in_progress: 'قيد التنفيذ',
  completed: 'مكتمل',
  cancelled: 'ملغي',
}

const activityLabels: Record<string, string> = {
  'operation.created': 'تم إنشاء مشروع التشغيل',
  'operation.backfilled': 'تم إنشاء مشروع تشغيل للحجز السابق',
  'operation.completed': 'تم إكمال الحفل',
  'tasks.seeded': 'تم إنشاء مهام تشغيلية تلقائية',
  'task.created': 'تم إنشاء مهمة',
  'task.updated': 'تم تحديث مهمة',
  'task.completed': 'اكتملت مهمة',
  'task.approved': 'تم اعتماد مهمة',
  'task.commented': 'تمت إضافة تعليق',
  'member.assigned': 'تم تعيين عضو',
  'member.removed': 'تمت إزالة عضو',
  'attachment.uploaded': 'تم رفع ملف',
}

const emptyTaskForm = {
  title: '',
  description: '',
  priority: 'medium',
  assigned_to: '',
  start_at: '',
  due_at: '',
  approval_required: false,
}

export default function OperationDetailPage() {
  const { operationId = '' } = useParams()
  const [searchParams] = useSearchParams()
  const qc = useQueryClient()
  const initialTab = (searchParams.get('tab') || 'overview') as OperationTab
  const [tab, setTab] = useState<OperationTab>(initialTab)
  const [taskDialog, setTaskDialog] = useState(false)
  const [taskForm, setTaskForm] = useState(emptyTaskForm)
  const [memberToAdd, setMemberToAdd] = useState('')
  const canManageOperations = usePermission(PERM.OPERATIONS_MANAGE)
  const canManageMembers = usePermission(PERM.OPERATIONS_MEMBERS)
  const canManageAttachments = usePermission(PERM.OPERATIONS_ATTACHMENTS)
  const canViewOverview = usePermission(PERM.OPERATION_TAB_OVERVIEW)
  const canViewTasks = usePermission(PERM.OPERATION_TAB_TASKS)
  const canViewTeam = usePermission(PERM.OPERATION_TAB_TEAM)
  const canViewGuests = usePermission(PERM.OPERATION_TAB_GUESTS)
  const canViewGates = usePermission(PERM.OPERATION_TAB_GATES)
  const canViewLive = usePermission(PERM.OPERATION_TAB_LIVE)
  const canViewFiles = usePermission(PERM.OPERATION_TAB_FILES)
  const canViewActivity = usePermission(PERM.OPERATION_TAB_ACTIVITY)
  const allowedOperationTabs = useMemo<OperationTab[]>(() => [
    ...(canViewOverview ? ['overview' as const] : []),
    ...(canViewTasks ? ['tasks' as const] : []),
    ...(canViewTeam ? ['team' as const] : []),
    ...(canViewGuests ? ['guests' as const] : []),
    ...(canViewGates ? ['gates' as const] : []),
    ...(canViewLive ? ['live' as const] : []),
    ...(canViewFiles ? ['files' as const] : []),
    ...(canViewActivity ? ['activity' as const] : []),
  ], [
    canViewActivity,
    canViewFiles,
    canViewGates,
    canViewGuests,
    canViewLive,
    canViewOverview,
    canViewTasks,
    canViewTeam,
  ])

  useEffect(() => {
    if (allowedOperationTabs.length && !allowedOperationTabs.includes(tab)) {
      setTab(allowedOperationTabs[0])
    }
  }, [allowedOperationTabs, tab])

  const query = useQuery({
    queryKey: ['operation', operationId],
    queryFn: () => operationsAPI.detail(operationId),
    enabled: !!operationId && allowedOperationTabs.length > 0,
  })

  const groups = useQuery({
    queryKey: ['booking-groups'],
    queryFn: () => bookingsAPI.groups(),
    enabled: tab === 'team',
  })

  const teamMembers = useQuery({
    queryKey: ['booking-team-members'],
    queryFn: () => usersAPI.list(),
    enabled: tab === 'team' || taskDialog,
  })

  const insights = useQuery({
    queryKey: ['operation-insights', operationId, 'overview'],
    queryFn: () => operationsAPI.eventInsights(operationId, 'overview'),
    enabled: !!operationId && allowedOperationTabs.includes('overview'),
    refetchInterval: 15000,
  })

  const refresh = () => qc.invalidateQueries({ queryKey: ['operation', operationId] })

  const taskUpdate = useMutation({
    mutationFn: ({ id, status }: { id: string; status: TaskStatus }) =>
      operationsAPI.updateTask(operationId, id, { status }),
    onSuccess: () => {
      refresh()
      toast.success('تم تحديث المهمة')
    },
    onError: (e: any) => toast.apiError('تعذر تحديث المهمة', e),
  })

  const taskCreate = useMutation({
    mutationFn: () =>
      operationsAPI.createTask(operationId, {
        title: taskForm.title.trim(),
        description: taskForm.description.trim() || undefined,
        priority: taskForm.priority,
        assigned_to: taskForm.assigned_to || undefined,
        start_at: taskForm.start_at || undefined,
        due_at: taskForm.due_at || undefined,
        approval_required: taskForm.approval_required,
      }),
    onSuccess: () => {
      refresh()
      toast.success('تم إنشاء المهمة')
      setTaskDialog(false)
      setTaskForm(emptyTaskForm)
    },
    onError: (e: any) => toast.apiError('تعذر إنشاء المهمة', e),
  })

  const upload = useMutation({
    mutationFn: (file: File) => operationsAPI.upload(operationId, file),
    onSuccess: () => {
      refresh()
      toast.success('تم رفع الملف')
    },
    onError: (e: any) => toast.apiError('تعذر رفع الملف', e),
  })

  if (query.isLoading) {
    return (
      <WorkspaceShell title="مشروع الحفل" subtitle="جار التحميل">
        <div className="operation-empty">جار تحميل مشروع الحفل...</div>
      </WorkspaceShell>
    )
  }

  if (query.isError || !query.data) {
    return (
      <WorkspaceShell title="تعذر فتح المشروع" subtitle="تحقق من صلاحيات الحساب">
        <div className="operation-empty">لا يمكن الوصول إلى مشروع هذا الحفل.</div>
      </WorkspaceShell>
    )
  }

  const op = query.data
  const canManage = op.my_role === 'manager' || op.my_role === 'lead'
  const currentMemberIds = new Set(op.members.map((m) => m.user_id))
  const availableMembers = (teamMembers.data || []).filter((m) => m.status === 'active' && !currentMemberIds.has(m.user_id))
  const doneTasks = op.tasks.filter((t) => t.status === 'done').length
  const blockedTasks = op.tasks.filter((t) => t.status === 'blocked').length
  const activeTasks = op.tasks.filter((t) => t.status === 'in_progress').length
  const invitationStats = insights.data?.invitations || {}
  const checkedIn = Number(invitationStats.checked_in || 0)
  const totalInvitations = Number(invitationStats.total || 0)
  const expectedGuests = Number(op.guest_count || 0)
  const attendanceRate = totalInvitations > 0 ? Math.round((checkedIn / totalInvitations) * 100) : 0
  const nextTasks = op.tasks.filter((t) => t.status !== 'done').slice(0, 4)
  const recentActivity = op.activity.slice(0, 5)
  const operationTabs = [
    ['overview', 'نظرة عامة', LayoutDashboard],
    ['tasks', 'المهام التنفيذية', ClipboardList],
    ['team', 'فريق العمل', Users],
    ['guests', 'الضيوف والدعوات', Users],
    ['gates', 'البوابات الميدانية', DoorOpen],
    ['live', 'المتابعة المباشرة', Radio],
    ['files', 'المرفقات والملفات', FileText],
    ['activity', 'سجل النشاط', History],
  ] as const

  const addMember = async () => {
    if (!memberToAdd) return
    try {
      await operationsAPI.setMember(operationId, memberToAdd, 'member')
      refresh()
      toast.success('تمت إضافة العضو للحفل')
      setMemberToAdd('')
    } catch (e: any) {
      toast.apiError('تعذرت إضافة العضو', e)
    }
  }

  return (
    <WorkspaceShell
      title={op.title}
      subtitle={`مشروع تشغيل الحفل - ${op.requester_name}`}
      actions={<Link className="operation-back" to="/teams">العودة للحفلات</Link>}
    >
      <section className="operation-detail-layout">
        <main className="operation-detail-layout__content">
      {tab === 'overview' && (
        <section className="operation-home">
      <section className="operation-command">
        <div className="operation-command__main">
          <span className="operation-status">{operationStatusLabels[op.status] || op.status}</span>
          <h2>{op.title}</h2>
          <p>{op.event_description || op.services || 'مساحة متابعة تشغيلية تجمع تفاصيل الحفل والمهام والفريق والحضور في مكان واحد.'}</p>
          <div className="operation-command__meta">
            <span><CalendarDays size={15} />{new Date(op.starts_at).toLocaleString('ar')}</span>
            <span><MapPin size={15} />{op.location || 'الموقع غير محدد'}</span>
            <span><Phone size={15} />{op.contact_name} - {op.contact_phone}</span>
          </div>
        </div>
        <div className="operation-command__progress">
          <strong>{op.progress || 0}%</strong>
          <span>إنجاز التشغيل</span>
          <progress value={op.progress || 0} max={100} />
        </div>
      </section>

      <section className="operation-kpi-grid">
        <article><ClipboardList /><span>المهام</span><strong>{doneTasks}/{op.tasks.length}</strong><small>{activeTasks} قيد التنفيذ، {blockedTasks} متوقفة</small></article>
        <article><Users /><span>فريق العمل</span><strong>{op.members.length}</strong><small>مدير، قادة، وأعضاء تشغيل</small></article>
        <article><DoorOpen /><span>البوابات</span><strong>{insights.data?.gates.length || 0}</strong><small>{insights.data?.gates.filter((g) => g.is_active).length || 0} مفعلة</small></article>
        <article><CheckCircle2 /><span>الحضور</span><strong>{attendanceRate}%</strong><small>{checkedIn} من {totalInvitations} دعوة مولّدة · الإجمالي {expectedGuests} دعوة</small></article>
        <article><Paperclip /><span>الملفات</span><strong>{op.attachments.length}</strong><small>مرفقات ومستندات تشغيل</small></article>
        <article><Activity /><span>آخر متابعة</span><strong>{recentActivity.length}</strong><small>سجل نشاطات حديث</small></article>
      </section>

      <section className="operation-follow-grid">
        <article className="operation-follow-card">
          <div className="operation-follow-card__head"><h3>الخطوات القادمة</h3><button onClick={() => setTab('tasks')}>فتح المهام</button></div>
          {nextTasks.map((task) => <div className="operation-mini-row" key={task.id}><span>{task.title}</span><b>{taskLabels[task.status]}</b></div>)}
          {!nextTasks.length && <div className="operation-mini-empty">لا توجد مهام مفتوحة حاليًا.</div>}
        </article>
        <article className="operation-follow-card">
          <div className="operation-follow-card__head"><h3>توزيع الفريق</h3><button onClick={() => setTab('team')}>إدارة الفريق</button></div>
          {op.members.slice(0, 5).map((member) => <div className="operation-mini-row" key={member.user_id}><span>{member.full_name || member.email}</span><b>{roleLabels[member.role] || member.role}</b></div>)}
          {!op.members.length && <div className="operation-mini-empty">لم يتم تعيين أعضاء بعد.</div>}
        </article>
        <article className="operation-follow-card">
          <div className="operation-follow-card__head"><h3>الحضور والبوابات</h3><button onClick={() => setTab('live')}>متابعة مباشرة</button></div>
          <div className="operation-mini-row"><span>الدعوات المولّدة</span><b>{totalInvitations}</b></div>
          <div className="operation-mini-row"><span>إجمالي الدعوات</span><b>{expectedGuests}</b></div>
          <div className="operation-mini-row"><span>تم التحضير</span><b>{checkedIn}</b></div>
          <div className="operation-mini-row"><span>المسحات</span><b>{Number(invitationStats.total_scans || 0)}</b></div>
        </article>
      </section>

        <div className="operation-overview">
          <article><CalendarDays /><span>موعد البداية</span><strong>{new Date(op.starts_at).toLocaleString('ar')}</strong></article>
          <article><MapPin /><span>الموقع الجغرافي</span><strong>{op.location || 'غير محدد'}</strong></article>
          <article><Users /><span>إجمالي الدعوات</span><strong>{op.guest_count} دعوة</strong></article>
          <article><Phone /><span>جهة التواصل</span><strong>{op.contact_name} - {op.contact_phone}</strong></article>
          <div className="operation-brief">
            <h3>متطلبات الحفل والخدمات</h3>
            <p>{op.services || 'لم تحدد متطلبات إضافية.'}</p>
            <h3>الملاحظات والتعليمات</h3>
            <p>{op.notes || 'لا توجد ملاحظات.'}</p>
          </div>
        </div>
        </section>
      )}

      {(tab === 'guests' || tab === 'gates' || tab === 'live') && <EventInsightsPanel operationId={operationId} active={tab} />}

      {tab === 'tasks' && (
        <>
          <div className="operation-section-head">
            <h2>مهام التنفيذ التشغيلية</h2>
            {canManage && canManageOperations && <button onClick={() => setTaskDialog(true)}><Plus /> مهمة جديدة</button>}
          </div>
          <div className="operation-cards">
            {op.tasks.map((task) => (
              <article key={task.id}>
                <div>
                  <strong>{task.title}</strong>
                  <small>{task.assignee_name || 'غير مسندة'} - {task.priority}</small>
                </div>
                <select value={task.status} onChange={(e) => taskUpdate.mutate({ id: task.id, status: e.target.value as TaskStatus })}>
                  {Object.entries(taskLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </article>
            ))}
          </div>
          {!op.tasks.length && <div className="operation-empty">لا توجد مهام حتى الآن.</div>}
        </>
      )}

      {tab === 'team' && (
        <>
          <div className="operation-section-head">
            <h2>فريق تشغيل الحفل</h2>
            <span>رتبتك في المشروع: {roleLabels[op.my_role] || op.my_role}</span>
          </div>
          <div className="operation-cards">
            {op.members.map((member) => (
              <article key={member.user_id}>
                <div>
                  <strong>{member.full_name || member.email}</strong>
                  <small>{member.email}</small>
                </div>
                {op.my_role === 'manager' ? (
                  <select
                    value={member.role}
                    onChange={(e) =>
                      operationsAPI
                        .setMember(operationId, member.user_id, e.target.value as any)
                        .then(() => {
                          refresh()
                          toast.success('تم تحديث دور العضو')
                        })
                        .catch((err: any) => toast.apiError('تعذر تحديث الدور', err))
                    }
                  >
                    <option value="manager">مدير الحفل</option>
                    <option value="lead">قائد مجموعة</option>
                    <option value="member">عضو تشغيل</option>
                  </select>
                ) : (
                  <b>{roleLabels[member.role] || member.role}</b>
                )}
              </article>
            ))}
          </div>

          {op.my_role === 'manager' && (
            <div className="operation-inline-panel">
              <div>
                <strong>إضافة عضو مباشر للحفل</strong>
                <span>اختر عضوًا من حسابات فريق التنظيم ثم أضفه كمشغل في هذا الحفل.</span>
              </div>
              <select value={memberToAdd} onChange={(e) => setMemberToAdd(e.target.value)}>
                <option value="">اختر عضوًا لإضافته...</option>
                {availableMembers.map((m) => <option key={m.user_id} value={m.user_id}>{m.full_name || m.email || m.user_id}</option>)}
              </select>
              {canManageMembers && <button disabled={!memberToAdd} onClick={addMember}><UserPlus size={16} /> إضافة للحفل</button>}
            </div>
          )}

          {op.my_role === 'manager' && op.booking_id ? (
            <div className="operation-inline-panel">
              <div>
                <strong>إسناد مجموعة تشغيلية كاملة</strong>
                <span>سيتم إلحاق جميع أعضاء المجموعة المحددة بفريق عمل الحفل.</span>
              </div>
              <select
                defaultValue=""
                onChange={async (e) => {
                  if (e.target.value) {
                    try {
                      await bookingsAPI.assignGroup(e.target.value, op.booking_id!)
                      toast.success('تم إسناد المجموعة للفريق')
                      refresh()
                    } catch (err: any) {
                      toast.apiError('تعذر إسناد المجموعة', err)
                    }
                  }
                  e.target.value = ''
                }}
              >
                <option value="">اختر مجموعة لإسناد موظفيها...</option>
                {groups.data?.map((group) => <option key={group.id} value={group.id}>{group.name} ({group.members_count} أعضاء)</option>)}
              </select>
              <span />
            </div>
          ) : null}
        </>
      )}

      {tab === 'files' && (
        <>
          <div className="operation-section-head">
            <h2>مرفقات وملفات الحفل</h2>
            {canManageAttachments && <label className="operation-upload">
              <FileUp size={16} /> رفع ملف
              <input hidden type="file" accept=".pdf,.jpg,.jpeg,.png,.webp,.docx" onChange={(e) => { const file = e.target.files?.[0]; if (file) upload.mutate(file) }} />
            </label>}
          </div>
          <div className="operation-cards">
            {op.attachments.map((file) => (
              <a href={file.download_url} target="_blank" rel="noreferrer" key={file.id}>
                <strong>{file.file_name}</strong>
                <small>{Math.ceil(file.size_bytes / 1024)} KB</small>
              </a>
            ))}
          </div>
          {!op.attachments.length && <div className="operation-empty">لا توجد مرفقات حتى الآن.</div>}
        </>
      )}

      {tab === 'activity' && (
        <div className="operation-timeline">
          {op.activity.map((item) => (
            <article key={item.id}>
              <CheckCircle2 />
              <div>
                <strong>{activityLabels[item.action] || item.action}</strong>
                <span>{item.actor_name || 'نظام الحجز'} - {new Date(item.created_at).toLocaleString('ar')}</span>
              </div>
            </article>
          ))}
          {!op.activity.length && <div className="operation-empty">لا توجد سجلات نشاط مسجلة للمشروع بعد.</div>}
        </div>
      )}

        </main>

        <aside className="operation-side-nav" aria-label="أقسام إدارة الحفل">
          <div className="operation-side-nav__header">
            <span>إدارة الحفل</span>
            <strong>{operationStatusLabels[op.status] || op.status}</strong>
          </div>
          <nav>
            {operationTabs
              .filter(([key]) => allowedOperationTabs.includes(key))
              .map(([key, label, Icon]) => (
                <button
                  className={tab === key ? 'active' : ''}
                  onClick={() => setTab(key)}
                  key={key}
                  type="button"
                >
                  <Icon />
                  <span>{label}</span>
                </button>
              ))}
          </nav>
        </aside>
      </section>

      {taskDialog && (
        <ConfirmDialog
          isOpen
          title="إنشاء مهمة تشغيلية"
          message="أدخل تفاصيل المهمة وحدد المسؤول والموعد والأولوية."
          confirmLabel="إنشاء المهمة"
          isPending={taskCreate.isPending}
          onCancel={() => { setTaskDialog(false); setTaskForm(emptyTaskForm) }}
          onConfirm={() => taskForm.title.trim() && taskCreate.mutate()}
        >
          <div className="operation-task-form">
            <input className="confirm-dialog__input" placeholder="عنوان المهمة" value={taskForm.title} onChange={(e) => setTaskForm((value) => ({ ...value, title: e.target.value }))} autoFocus />
            <textarea className="confirm-dialog__textarea" placeholder="وصف المهمة أو تعليمات التنفيذ" value={taskForm.description} onChange={(e) => setTaskForm((value) => ({ ...value, description: e.target.value }))} />
            <div className="operation-task-form__grid">
              <select value={taskForm.priority} onChange={(e) => setTaskForm((value) => ({ ...value, priority: e.target.value }))}>
                <option value="low">أولوية منخفضة</option>
                <option value="medium">أولوية متوسطة</option>
                <option value="high">أولوية عالية</option>
                <option value="urgent">عاجلة</option>
              </select>
              <select value={taskForm.assigned_to} onChange={(e) => setTaskForm((value) => ({ ...value, assigned_to: e.target.value }))}>
                <option value="">بدون مسؤول محدد</option>
                {op.members.map((member) => <option key={member.user_id} value={member.user_id}>{member.full_name || member.email}</option>)}
              </select>
              <input type="datetime-local" value={taskForm.start_at} onChange={(e) => setTaskForm((value) => ({ ...value, start_at: e.target.value }))} />
              <input type="datetime-local" value={taskForm.due_at} onChange={(e) => setTaskForm((value) => ({ ...value, due_at: e.target.value }))} />
            </div>
            <label className="operation-check"><input type="checkbox" checked={taskForm.approval_required} onChange={(e) => setTaskForm((value) => ({ ...value, approval_required: e.target.checked }))} /> تتطلب اعتماد مدير الحفل قبل الإغلاق</label>
          </div>
        </ConfirmDialog>
      )}
    </WorkspaceShell>
  )
}
