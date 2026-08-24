import { useDeferredValue, useMemo, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Shield,
  Users,
  Plus,
  Search,
  Trash2,
  Edit3,
  CheckSquare,
  Square,
  X,
  AlertCircle,
  Loader2,
  RefreshCcw,
  Crown,
  User,
  UserCheck,
  Clock3,
  RotateCcw,
  Mail,
  LockKeyhole,
  UserPlus,
} from 'lucide-react'
import { WorkspaceShell } from '@features/workspace/components/WorkspaceShell'
import { Can, PERM, usePermission } from '@shared/permissions'
import { usersAPI } from '../api/usersApi'
import { useAuthStore } from '@features/auth/store/authStore'
import type { UserMember, UpdateMemberRequest } from '../types'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import '../pages/users.css'

// ═══════════════════════════════════════════════════════
// CONSTANTS
// ═══════════════════════════════════════════════════════
const roleLabel: Record<string, string> = {
  owner: 'مالك',
  admin: 'مدير',
  member: 'عضو',
  viewer: 'مشاهد',
}

const statusLabel: Record<string, string> = {
  active: 'نشط',
  invited: 'بانتظار القبول',
  disabled: 'موقوف',
}

function errorMessage(error: unknown) {
  const fallback = 'تعذر إتمام العملية. تحقق من البيانات وحاول مرة أخرى.'
  if (!error || typeof error !== 'object') return fallback
  const candidate = error as { response?: { data?: { detail?: string } }; message?: string }
  return candidate.response?.data?.detail || candidate.message || fallback
}

const roleIcons: Record<string, typeof Crown> = {
  owner: Crown,
  admin: Shield,
  member: User,
  viewer: User,
}

const dateFmt = new Intl.DateTimeFormat('ar', { dateStyle: 'medium' })

function formatDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'غير متوفر' : dateFmt.format(date)
}

// ═══════════════════════════════════════════════════════
// DIALOG: Add Member
// ═══════════════════════════════════════════════════════
const createMemberSchema = z.object({
  full_name: z.string().max(120, 'الاسم طويل جدًا').optional(),
  email: z.string().email('بريد إلكتروني غير صالح'),
  temporary_password: z.string().max(128, 'كلمة المرور طويلة جدًا').optional(),
  role: z.enum(['admin', 'member', 'viewer']),
})

type CreateMemberForm = z.infer<typeof createMemberSchema>

function AddMemberDialog({
  isOpen,
  onClose,
  onSubmit,
  isLoading,
  error,
}: {
  isOpen: boolean
  onClose: () => void
  onSubmit: (data: CreateMemberForm, mode: 'invite' | 'direct') => void
  isLoading: boolean
  error?: string | null
}) {
  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors, isValid, isDirty },
  } = useForm<CreateMemberForm>({
    resolver: zodResolver(createMemberSchema),
    defaultValues: { role: 'member' },
    mode: 'onChange',
  })
  const [mode, setMode] = useState<'invite' | 'direct'>('invite')

  // Reset form when dialog closes
  const handleClose = () => {
    reset()
    onClose()
  }

  const onFormSubmit = (data: CreateMemberForm) => {
    if (mode === 'invite' && (data.full_name || '').trim().length < 2) {
      setError('full_name', { message: 'الاسم يجب أن يكون حرفين على الأقل' })
      return
    }
    if (mode === 'direct' && data.temporary_password && data.temporary_password.length < 8) {
      setError('temporary_password', { message: 'كلمة المرور المؤقتة يجب ألا تقل عن 8 أحرف' })
      return
    }
    onSubmit(data, mode)
  }

  if (!isOpen) return null

  return (
    <div className="dialog-overlay" onClick={handleClose}>
      <motion.div
        className="dialog-content"
        initial={{ opacity: 0, scale: 0.95, y: 20 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95, y: 20 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="dialog-header">
          <div><span className="dialog-eyebrow">إضافة إلى مساحة العمل</span><h3>{mode === 'invite' ? 'دعوة مستخدم جديد' : 'إضافة حساب موجود'}</h3></div>
          <button type="button" className="dialog-close" onClick={handleClose} aria-label="إغلاق"><X size={18} /></button>
        </div>

        <form
          onSubmit={handleSubmit(onFormSubmit)}
          className="dialog-form"
          noValidate
        >
          <div className="member-add-mode" role="tablist" aria-label="طريقة إضافة المستخدم">
            <button type="button" className={mode === 'invite' ? 'active' : ''} onClick={() => setMode('invite')}><Mail size={16} /> إرسال دعوة</button>
            <button type="button" className={mode === 'direct' ? 'active' : ''} onClick={() => setMode('direct')}><UserPlus size={16} /> إضافة مباشرة</button>
          </div>
          <p className="member-add-help">{mode === 'invite' ? 'سنرسل رابطًا آمنًا إلى البريد، ويُضاف المستخدم بعد قبوله.' : 'لإنشاء حساب جديد أدخل الاسم وكلمة مرور مؤقتة؛ سنرسل بيانات الدخول إلى بريده. إذا كان الحساب موجودًا فاترك كلمة المرور فارغة.'}</p>
          {error && <div className="dialog-inline-error"><AlertCircle size={16} />{error}</div>}
          {(mode === 'invite' || mode === 'direct') && (
            <div className="form-field">
              <label>الاسم الكامل {mode === 'direct' && <span className="field-optional">(مطلوب للحساب الجديد)</span>}</label>
              <input
                {...register('full_name')}
                placeholder="محمد العبدالله"
                className={errors.full_name ? 'error' : ''}
                disabled={isLoading}
              />
              {errors.full_name && (
                <span className="form-error">{errors.full_name.message}</span>
              )}
            </div>
          )}

          <div className="form-field">
            <label>البريد الإلكتروني</label>
            <input
              {...register('email')}
              type="email"
              placeholder="user@company.com"
              dir="ltr"
              className={errors.email ? 'error' : ''}
              disabled={isLoading}
            />
            {errors.email && (
              <span className="form-error">{errors.email.message}</span>
            )}
          </div>

          {mode === 'direct' && (
            <div className="form-field">
              <label>كلمة المرور المؤقتة <span className="field-optional">(للحساب الجديد)</span></label>
              <input
                {...register('temporary_password')}
                type="password"
                dir="ltr"
                autoComplete="new-password"
                placeholder="8 أحرف على الأقل"
                className={errors.temporary_password ? 'error' : ''}
                disabled={isLoading}
              />
              {errors.temporary_password && <span className="form-error">{errors.temporary_password.message}</span>}
              <span className="form-hint">ستُرسل إلى البريد، ويُنصح المستخدم بتغييرها فور تسجيل الدخول.</span>
            </div>
          )}

          <div className="form-field">
            <label>مستوى الوصول</label>
            <select {...register('role')} className="form-select" disabled={isLoading}>
              <option value="admin">مدير — إدارة الأعضاء والإعدادات</option>
              <option value="member">عضو — تنفيذ المهام اليومية</option>
              <option value="viewer">مشاهد — وصول للقراءة فقط</option>
            </select>
            <span className="form-hint">يمكن تعديل مستوى الوصول لاحقًا وفق صلاحياتك.</span>
          </div>

          <div className="dialog-actions">
            <button
              type="button"
              className="btn btn-ghost"
              onClick={handleClose}
              disabled={isLoading}
            >
              إلغاء
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={isLoading || !isValid || !isDirty}
            >
              {isLoading ? (
                <><Loader2 size={16} className="spin" /> {mode === 'invite' ? 'جارٍ إرسال الدعوة…' : 'جارٍ إضافة المستخدم…'}</>
              ) : (
                mode === 'invite' ? <><Mail size={16} /> إرسال الدعوة</> : <><UserPlus size={16} /> إضافة مباشرة</>
              )}
            </button>
          </div>
        </form>
      </motion.div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════
// DIALOG: Edit Member
// ═══════════════════════════════════════════════════════
function EditMemberDialog({
  isOpen,
  onClose,
  member,
  onSubmit,
  isLoading,
}: {
  isOpen: boolean
  onClose: () => void
  member: UserMember | null
  onSubmit: (data: UpdateMemberRequest) => void
  isLoading: boolean
}) {
  const [role, setRole] = useState<UserMember['role']>(member?.role || 'member')
  const [status, setStatus] = useState<UserMember['status']>(member?.status || 'active')

  if (!isOpen || !member) return null

  return (
    <div className="dialog-overlay" onClick={onClose}>
      <motion.div
        className="dialog-content"
        initial={{ opacity: 0, scale: 0.95, y: 20 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95, y: 20 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="dialog-header">
          <div><span className="dialog-eyebrow">إدارة الوصول</span><h3>تعديل حساب المستخدم</h3></div>
          <button type="button" className="dialog-close" onClick={onClose} aria-label="إغلاق"><X size={18} /></button>
        </div>

        <div className="dialog-form">
          <div className="member-preview">
            <div className="member-avatar large">{(member.full_name || 'U').slice(0, 1)}</div>
            <div>
              <strong>{member.full_name || 'مستخدم بدون اسم'}</strong>
              <span>{member.email || 'لا يوجد بريد إلكتروني مسجل'}</span>
            </div>
          </div>

          <div className="form-field">
            <label>مستوى الوصول</label>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as UserMember['role'])}
              className="form-select"
            >
              {member.role === 'owner' && <option value="owner">مالك</option>}
              <option value="admin">مدير</option>
              <option value="member">عضو</option>
              <option value="viewer">مشاهد</option>
            </select>
            {member.role === 'owner' && <span className="form-hint">يمكن لمالك المؤسسة تغيير دور مالك آخر، بشرط بقاء مالك نشط واحد على الأقل.</span>}
          </div>

          <div className="form-field">
            <label>الحالة</label>
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value as UserMember['status'])}
              className="form-select"
            >
              <option value="active">نشط</option>
              <option value="disabled">موقوف</option>
            </select>
            {member.role === 'owner' && <span className="form-hint">لن يسمح النظام بإيقاف آخر مالك نشط للمؤسسة.</span>}
          </div>

          <div className="dialog-actions">
            <button type="button" className="btn btn-ghost" onClick={onClose}>إلغاء</button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={isLoading || (role === member.role && status === member.status)}
              onClick={() => onSubmit({ role: role as UserMember['role'], status: status as UserMember['status'] })}
            >
              {isLoading ? <><Loader2 size={16} className="spin" /> جاري الحفظ...</> : <><Edit3 size={16} /> حفظ التغييرات</>}
            </button>
          </div>
        </div>
      </motion.div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════
// DIALOG: Confirm Delete
// ═══════════════════════════════════════════════════════
function ConfirmDeleteDialog({
  isOpen,
  onClose,
  onConfirm,
  isLoading,
  title,
  message,
}: {
  isOpen: boolean
  onClose: () => void
  onConfirm: () => void
  isLoading: boolean
  title: string
  message: string
}) {
  if (!isOpen) return null

  return (
    <div className="dialog-overlay" onClick={onClose}>
      <motion.div
        className="dialog-content dialog-content--danger"
        initial={{ opacity: 0, scale: 0.95, y: 20 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95, y: 20 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="dialog-header dialog-header--danger">
          <div className="dialog-icon">
            <AlertCircle size={24} />
          </div>
          <h3>{title}</h3>
          <button className="dialog-close" onClick={onClose}><X size={18} /></button>
        </div>

        <p className="dialog-message">{message}</p>

        <div className="dialog-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>إلغاء</button>
          <button
            type="button"
            className="btn btn-danger"
            disabled={isLoading}
            onClick={onConfirm}
          >
            {isLoading ? <><Loader2 size={16} className="spin" /> جاري الحذف...</> : <><Trash2 size={16} /> تأكيد الحذف</>}
          </button>
        </div>
      </motion.div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════
export default function UsersPage() {
  const currentTenantId = useAuthStore(s => s.currentTenantId)

  // Guard
  const hasAccess = usePermission(PERM.NAV_USERS)
  const currentUserId = useAuthStore(s => s.user?.id)
  const currentTenant = useAuthStore(s => s.tenants.find(t => t.tenant_id === currentTenantId))
  const queryClient = useQueryClient()
  const canEditMembers = usePermission(PERM.MEMBER_EDIT)
  const canDeleteMembers = usePermission(PERM.MEMBER_DELETE)

  // ── State ──
  const [search, setSearch] = useState('')
  const [selectedUsers, setSelectedUsers] = useState<Set<string>>(new Set())
  const [showAddDialog, setShowAddDialog] = useState(false)
  const [editingMember, setEditingMember] = useState<UserMember | null>(null)
  const [deletingMember, setDeletingMember] = useState<UserMember | null>(null)
  const [showBulkDelete, setShowBulkDelete] = useState(false)
  const [roleFilter, setRoleFilter] = useState<string>('all')
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null)

  // ── Queries ──
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['users', currentTenantId],
    queryFn: usersAPI.list,
    enabled: Boolean(currentTenantId) && hasAccess,
  })

  const members = useMemo(() => data ?? [], [data])

  // ── Mutations ──
  const createMutation = useMutation({
    mutationFn: async ({ data, mode }: { data: CreateMemberForm; mode: 'invite' | 'direct' }) => {
      if (mode === 'invite') {
        await usersAPI.create({ ...data, full_name: (data.full_name || '').trim() })
        return
      }
      await usersAPI.addDirect({
        email: data.email,
        full_name: (data.full_name || '').trim(),
        temporary_password: data.temporary_password || undefined,
        role: data.role,
      })
    },
    onSuccess: (_result, variables) => {
      queryClient.invalidateQueries({ queryKey: ['users', currentTenantId] })
      queryClient.invalidateQueries({ queryKey: ['dashboard', currentTenantId] })
      setShowAddDialog(false)
      setFeedback({ type: 'success', message: variables.mode === 'invite' ? 'تم إرسال الدعوة بنجاح. سيُضاف المستخدم بعد قبولها.' : 'تمت إضافة المستخدم مباشرة، وأُرسلت بيانات الدخول إذا تم إنشاء حساب جديد.' })
    },
    onError: (error) => setFeedback({ type: 'error', message: errorMessage(error) }),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: string; body: UpdateMemberRequest }) =>
      usersAPI.update(id, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users', currentTenantId] })
      queryClient.invalidateQueries({ queryKey: ['dashboard', currentTenantId] })
      setEditingMember(null)
      setFeedback({ type: 'success', message: 'تم تحديث مستوى الوصول وحالة الحساب.' })
    },
    onError: (error) => setFeedback({ type: 'error', message: errorMessage(error) }),
  })

  const deleteMutation = useMutation({
    mutationFn: usersAPI.remove,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users', currentTenantId] })
      queryClient.invalidateQueries({ queryKey: ['dashboard', currentTenantId] })
      setDeletingMember(null)
      setShowBulkDelete(false)
      setSelectedUsers(new Set())
      setFeedback({ type: 'success', message: 'تمت إزالة المستخدم من مساحة العمل.' })
    },
    onError: (error) => setFeedback({ type: 'error', message: errorMessage(error) }),
  })

  const bulkDeleteMutation = useMutation({
    mutationFn: usersAPI.bulkRemove,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users', currentTenantId] })
      queryClient.invalidateQueries({ queryKey: ['dashboard', currentTenantId] })
      setShowBulkDelete(false)
      setSelectedUsers(new Set())
      setFeedback({ type: 'success', message: 'تمت إزالة المستخدمين المحددين من مساحة العمل.' })
    },
    onError: (error) => setFeedback({ type: 'error', message: errorMessage(error) }),
  })

  // ── Filtering ──
  const deferredSearch = useDeferredValue(search)
  const normalizedSearch = deferredSearch.trim().toLowerCase()

  const filteredMembers = useMemo(() => {
    return members.filter((member) => {
      const matchesSearch = normalizedSearch
        ? (member.full_name || '').toLowerCase().includes(normalizedSearch) ||
          member.user_id.toLowerCase().includes(normalizedSearch) ||
          member.email?.toLowerCase().includes(normalizedSearch)
        : true

      const matchesRole = roleFilter === 'all' || member.role === roleFilter
      const matchesStatus = statusFilter === 'all' || member.status === statusFilter

      return matchesSearch && matchesRole && matchesStatus
    })
  }, [members, normalizedSearch, roleFilter, statusFilter])

  // ── Stats ──
  const stats = useMemo(() => ({
    total: members.length,
    active: members.filter(m => m.status === 'active').length,
    owners: members.filter(m => m.role === 'owner').length,
    admins: members.filter(m => m.role === 'admin').length,
    members: members.filter(m => m.role === 'member').length,
    viewers: members.filter(m => m.role === 'viewer').length,
    disabled: members.filter(m => m.status === 'disabled').length,
    invited: members.filter(m => m.status === 'invited').length,
  }), [members])

  if (!hasAccess) {
    return <Navigate to="/dashboard" replace />
  }

  // ── Selection ──
  const toggleSelection = (userId: string) => {
    const newSelected = new Set(selectedUsers)
    if (newSelected.has(userId)) {
      newSelected.delete(userId)
    } else {
      newSelected.add(userId)
    }
    setSelectedUsers(newSelected)
  }

  const toggleAll = () => {
    const selectableMembers = filteredMembers.filter(canDelete)
    if (selectedUsers.size === selectableMembers.length) {
      setSelectedUsers(new Set())
    } else {
      setSelectedUsers(new Set(selectableMembers.map(member => member.user_id)))
    }
  }

  const actorIsOwner = currentTenant?.role === 'owner'
  const canEdit = (member: UserMember) =>
    canEditMembers && member.user_id !== currentUserId && (member.role !== 'owner' || actorIsOwner)

  const canDelete = (member: UserMember) =>
    canDeleteMembers && member.user_id !== currentUserId && (member.role !== 'owner' || actorIsOwner)

  // ═══════════════════════════════════════════════════════
  // RENDER
  // ═══════════════════════════════════════════════════════
  return (
    <WorkspaceShell
      title="فريق المؤسسة"
      subtitle={`${currentTenant?.name || 'مساحة العمل'} · إدارة الحسابات والأدوار وحالة الوصول من مكان واحد`}
      actions={
        <div className="header-actions">
          <Can permission={PERM.MEMBER_CREATE}>
            <button
              className="btn btn-primary"
              onClick={() => setShowAddDialog(true)}
            >
              <Plus size={16} /> دعوة مستخدم
            </button>
          </Can>
          <button className="dash-icon-btn" onClick={() => refetch()} aria-label="تحديث">
            <RefreshCcw size={18} />
          </button>
        </div>
      }
    >
      {/* ── Stats ── */}
      <section className="dash-stats-grid users-stats-grid">
        <div className="dash-stat">
          <div className="dash-stat__icon"><Users size={20} /></div>
          <div>
            <span className="dash-stat__label">إجمالي الحسابات</span>
            <strong className="dash-stat__value">{stats.total}</strong>
            <span className="dash-stat__delta">{stats.active} نشط</span>
          </div>
        </div>
        <div className="dash-stat dash-stat--blue">
          <div className="dash-stat__icon"><UserCheck size={20} /></div>
          <div>
            <span className="dash-stat__label">الحسابات النشطة</span>
            <strong className="dash-stat__value">{stats.active}</strong>
            <span className="dash-stat__delta">يمكنها الدخول حاليًا</span>
          </div>
        </div>
        <div className="dash-stat dash-stat--gold">
          <div className="dash-stat__icon"><User size={20} /></div>
          <div>
            <span className="dash-stat__label">إدارة مساحة العمل</span>
            <strong className="dash-stat__value">{stats.owners + stats.admins}</strong>
            <span className="dash-stat__delta">{stats.owners} مالك · {stats.admins} مدير</span>
          </div>
        </div>
        <div className="dash-stat dash-stat--red">
          <div className="dash-stat__icon"><Clock3 size={20} /></div>
          <div>
            <span className="dash-stat__label">تحتاج متابعة</span>
            <strong className="dash-stat__value">{stats.invited + stats.disabled}</strong>
            <span className="dash-stat__delta">{stats.invited} دعوة معلّقة · {stats.disabled} موقوف</span>
          </div>
        </div>
      </section>

      <AnimatePresence>
        {feedback && (
          <motion.div className={`users-feedback users-feedback--${feedback.type}`} initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} role="status">
            {feedback.type === 'success' ? <UserCheck size={18} /> : <AlertCircle size={18} />}
            <span>{feedback.message}</span>
            <button type="button" onClick={() => setFeedback(null)} aria-label="إغلاق الرسالة"><X size={16} /></button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ── Table ── */}
      <section className="dash-panel users-directory-panel" aria-label="قائمة مستخدمي المؤسسة">
        {/* Toolbar */}
        <div className="users-toolbar">
          <div className="toolbar-search">
            <Search size={16} className="search-icon" />
            <input
              className="users-search"
              placeholder="ابحث باسم المستخدم أو بريده الإلكتروني…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          <div className="toolbar-filters">
            <select value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)} className="filter-select">
              <option value="all">جميع الأدوار</option>
              <option value="owner">مالك</option>
              <option value="admin">مدير</option>
              <option value="member">عضو</option>
              <option value="viewer">مشاهد</option>
            </select>

            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="filter-select">
              <option value="all">جميع الحالات</option>
              <option value="active">نشط</option>
              <option value="invited">بانتظار القبول</option>
              <option value="disabled">موقوف</option>
            </select>
          </div>

        </div>

        <div className="users-results-summary">
          <span>عرض <strong>{filteredMembers.length}</strong> من أصل <strong>{members.length}</strong> مستخدم</span>
          {(normalizedSearch || roleFilter !== 'all' || statusFilter !== 'all') && (
            <button type="button" onClick={() => { setSearch(''); setRoleFilter('all'); setStatusFilter('all') }}>
              <RotateCcw size={14} /> مسح عوامل التصفية
            </button>
          )}
        </div>

        {/* Bulk Actions */}
        <AnimatePresence>
          {selectedUsers.size > 0 && (
            <motion.div
              className="bulk-actions-bar"
              initial={{ opacity: 0, y: -20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
            >
              <span className="bulk-count">
                <CheckSquare size={16} /> {selectedUsers.size} محدد
              </span>
              <div className="bulk-buttons">
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => setShowBulkDelete(true)}
                >
                  <Trash2 size={14} /> حذف المحدد
                </button>
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => setSelectedUsers(new Set())}
                >
                  <X size={14} /> إلغاء التحديد
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Loading & Error */}
        {isLoading ? <div className="dash-empty">جار تحميل المستخدمين...</div> : null}
        {isError ? (
          <div className="dash-empty">
            <AlertCircle size={24} />
            <p>تعذر تحميل المستخدمين</p>
            <button className="btn btn-primary" onClick={() => refetch()}>إعادة المحاولة</button>
          </div>
        ) : null}

        {/* Table */}
        {!isLoading && !isError && (
          <div className="users-table-container">
            <div className="users-table">
              <div className="users-table__head">
                <span className="select-cell">
                  <button
                    className="checkbox-btn"
                    onClick={toggleAll}
                  >
                    {selectedUsers.size === filteredMembers.length && filteredMembers.length > 0
                      ? <CheckSquare size={18} />
                      : <Square size={18} />}
                  </button>
                </span>
                <span>الحساب</span>
                <span>مستوى الوصول</span>
                <span>حالة الحساب</span>
                <span>تاريخ الإضافة</span>
                <span className="actions-cell">الإجراءات</span>
              </div>

              {filteredMembers.length ? (
                filteredMembers.map((member) => {
                  const RoleIcon = roleIcons[member.role] || User
                  const isSelected = selectedUsers.has(member.user_id)
                  const canEditMember = canEdit(member)
                  const canDeleteMember = canDelete(member)

                  return (
                    <motion.div
                      className={`users-row ${isSelected ? 'users-row--selected' : ''}`}
                      key={member.user_id}
                      layout
                    >
                      <span className="select-cell">
                        <button
                          className="checkbox-btn"
                          onClick={() => toggleSelection(member.user_id)}
                          disabled={!canDeleteMember}
                          aria-label={`تحديد ${member.full_name || member.user_id}`}
                        >
                          {isSelected ? <CheckSquare size={18} /> : <Square size={18} />}
                        </button>
                      </span>

                      <div className="users-row__user">
                        <div className="member-avatar">{(member.full_name || 'U').slice(0, 1)}</div>
                        <div>
                          <strong>{member.full_name || 'مستخدم بدون اسم'}</strong>
                          <span>{member.email || 'لا يوجد بريد إلكتروني'}</span>
                        </div>
                      </div>

                      <span className={`users-chip users-chip--${member.role}`}>
                        <RoleIcon size={14} />
                        {roleLabel[member.role] || member.role}
                      </span>

                      <span className={`users-status users-status--${member.status}`}>
                        {statusLabel[member.status] || member.status}
                      </span>

                      <span className="date-cell">{formatDate(member.created_at)}</span>

                      <span className="actions-cell">
                        <div className="row-actions">
                          {canEditMember && (
                            <button
                              className="action-btn"
                              onClick={() => setEditingMember(member)}
                              title="تعديل الوصول"
                              aria-label={`تعديل ${member.full_name || 'المستخدم'}`}
                            >
                              <Edit3 size={14} />
                            </button>
                          )}
                          {canDeleteMember && (
                            <button
                              className="action-btn action-btn--danger"
                              onClick={() => setDeletingMember(member)}
                              title="إزالة من مساحة العمل"
                              aria-label={`إزالة ${member.full_name || 'المستخدم'}`}
                            >
                              <Trash2 size={14} />
                            </button>
                          )}
                          {!canEditMember && !canDeleteMember && (
                            <span className="protected-account" title={member.user_id === currentUserId ? 'هذا حسابك الحالي؛ عدّل بياناته من ملفي الشخصي في الإعدادات' : 'هذا الحساب محمي وفق صلاحياتك الحالية'}>
                              <LockKeyhole size={14} /> {member.user_id === currentUserId ? 'حسابك' : 'محمي'}
                            </span>
                          )}
                        </div>
                      </span>
                    </motion.div>
                  )
                })
              ) : (
                <div className="dash-empty">
                  {normalizedSearch || roleFilter !== 'all' || statusFilter !== 'all'
                    ? 'لا توجد حسابات تطابق البحث أو عوامل التصفية الحالية.'
                    : 'لا توجد حسابات مضافة بعد. ابدأ بدعوة أول مستخدم إلى مساحة العمل.'}
                </div>
              )}
            </div>
          </div>
        )}
      </section>

      {/* ── Dialogs ── */}
      <AnimatePresence>
        {showAddDialog && (
          <AddMemberDialog
            isOpen={showAddDialog}
            onClose={() => setShowAddDialog(false)}
            onSubmit={(data, mode) => createMutation.mutate({ data, mode })}
            isLoading={createMutation.isPending}
            error={createMutation.isError ? errorMessage(createMutation.error) : null}
          />
        )}

        {editingMember && (
          <EditMemberDialog
            isOpen={!!editingMember}
            onClose={() => setEditingMember(null)}
            member={editingMember}
            onSubmit={(body) =>
              updateMutation.mutate({ id: editingMember.user_id, body })
            }
            isLoading={updateMutation.isPending}
          />
        )}

        {deletingMember && (
          <ConfirmDeleteDialog
            isOpen={!!deletingMember}
            onClose={() => setDeletingMember(null)}
            onConfirm={() => deleteMutation.mutate(deletingMember.user_id)}
            isLoading={deleteMutation.isPending}
            title="حذف العضو"
            message={`هل أنت متأكد من حذف "${deletingMember.full_name || deletingMember.user_id}"؟ لا يمكن التراجع عن هذا الإجراء.`}
          />
        )}

        {showBulkDelete && (
          <ConfirmDeleteDialog
            isOpen={showBulkDelete}
            onClose={() => setShowBulkDelete(false)}
            onConfirm={() => bulkDeleteMutation.mutate(Array.from(selectedUsers))}
            isLoading={bulkDeleteMutation.isPending}
            title="حذف متعدد"
            message={`هل أنت متأكد من حذف ${selectedUsers.size} عضو؟ لا يمكن التراجع عن هذا الإجراء.`}
          />
        )}
      </AnimatePresence>
    </WorkspaceShell>
  )
}
