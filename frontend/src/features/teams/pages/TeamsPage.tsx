import { useMemo, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import {
  FolderKanban,
  Users,
  Plus,
  Edit3,
  Trash2,
  Archive,
  ArchiveRestore,
  UserPlus,
  UserMinus,
  X,
  AlertCircle,
  Loader2,
  RefreshCcw,
  Shield,
  ChevronDown,
  ChevronUp,
  Search,
} from 'lucide-react'
import { WorkspaceShell } from '@features/workspace/components/WorkspaceShell'
import { Can, PERM, usePermission } from '@shared/permissions'
import { teamsAPI } from '../api/teamsApi'
import { usersAPI } from '@features/users/api/usersApi'
import { useAuthStore } from '@features/auth/store/authStore'
import type { Team, TeamMember, CreateTeamRequest, UpdateTeamRequest, AddTeamMemberRequest } from '../types'
import type { UserMember } from '@features/users/types'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import '@features/users/pages/users.css'

// ═══════════════════════════════════════════════════════
// CONSTANTS
// ═══════════════════════════════════════════════════════
const teamRoleLabel: Record<string, string> = {
  lead: 'قائد',
  member: 'عضو',
  viewer: 'مشاهد',
}

const teamColors = [
  '#D4A32C', '#6366f1', '#8b5cf6', '#ec4899', '#f43f5e',
  '#ef4444', '#f97316', '#eab308', '#22c55e', '#06b6d4',
  '#3b82f6', '#a855f7',
]

// ═══════════════════════════════════════════════════════
// DIALOG: Create/Edit Team
// ═══════════════════════════════════════════════════════
const teamSchema = z.object({
  name: z.string().min(2, 'الاسم يجب أن يكون حرفين على الأقل').max(50, 'الاسم طويل جداً'),
  description: z.string().max(200, 'الوصف طويل جداً').optional(),
  color: z.string().default('#D4A32C'),
})

type TeamFormData = z.infer<typeof teamSchema>

function TeamDialog({
  isOpen,
  onClose,
  team,
  onSubmit,
  isLoading,
}: {
  isOpen: boolean
  onClose: () => void
  team?: Team | null
  onSubmit: (data: TeamFormData) => void
  isLoading: boolean
}) {
  const {
    register,
    handleSubmit,
    reset,
    watch,
    setValue,
    formState: { errors },
  } = useForm<TeamFormData>({
    resolver: zodResolver(teamSchema),
    defaultValues: {
      name: team?.name || '',
      description: team?.description || '',
      color: team?.color || '#D4A32C',
    },
  })

  const selectedColor = watch('color') || '#D4A32C'
  const isEditing = !!team

  if (!isOpen) return null

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
          <h3>{isEditing ? 'تعديل الفريق' : 'إنشاء فريق جديد'}</h3>
          <button className="dialog-close" onClick={onClose}><X size={18} /></button>
        </div>

        <form
          onSubmit={handleSubmit((data) => {
            onSubmit(data)
            if (!isEditing) reset()
          })}
          className="dialog-form"
        >
          <div className="form-field">
            <label>اسم الفريق</label>
            <input
              {...register('name')}
              placeholder="فريق التسويق"
              className={errors.name ? 'error' : ''}
            />
            {errors.name && <span className="form-error">{errors.name.message}</span>}
          </div>

          <div className="form-field">
            <label>الوصف (اختياري)</label>
            <input
              {...register('description')}
              placeholder="وصف مختصر للفريق ومهامه..."
            />
            {errors.description && <span className="form-error">{errors.description.message}</span>}
          </div>

          <div className="form-field">
            <label>اللون</label>
            <div className="color-picker">
              {teamColors.map((color) => (
                <button
                  key={color}
                  type="button"
                  className={`color-option ${selectedColor === color ? 'selected' : ''}`}
                  style={{ background: color }}
                  onClick={() => setValue('color', color)}
                />
              ))}
            </div>
            <input type="hidden" {...register('color')} />
          </div>

          <div className="dialog-actions">
            <button type="button" className="btn btn-ghost" onClick={onClose}>إلغاء</button>
            <button type="submit" className="btn btn-primary" disabled={isLoading}>
              {isLoading ? <><Loader2 size={16} className="spin" /> جاري الحفظ...</> : <>{isEditing ? <Edit3 size={16} /> : <Plus size={16} />} {isEditing ? 'حفظ التغييرات' : 'إنشاء الفريق'}</>}
            </button>
          </div>
        </form>
      </motion.div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════
// DIALOG: Add Member to Team
// ═══════════════════════════════════════════════════════
function AddTeamMemberDialog({
  isOpen,
  onClose,
  existingMembers,
  availableMembers,
  onSubmit,
  isLoading,
}: {
  isOpen: boolean
  onClose: () => void
  existingMembers: TeamMember[]
  availableMembers: UserMember[]
  onSubmit: (data: AddTeamMemberRequest) => void
  isLoading: boolean
}) {
  const [selectedUser, setSelectedUser] = useState('')
  const [role, setRole] = useState<AddTeamMemberRequest['role']>('member')
  const [search, setSearch] = useState('')

  const filteredAvailable = useMemo(() => {
    const existingIds = new Set(existingMembers.map((m) => m.user_id))
    return availableMembers.filter(
      (m) =>
        !existingIds.has(m.user_id) &&
        (m.full_name?.toLowerCase().includes(search.toLowerCase()) ||
          m.user_id.toLowerCase().includes(search.toLowerCase())),
    )
  }, [availableMembers, existingMembers, search])

  if (!isOpen) return null

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
          <h3>إضافة عضو للفريق</h3>
          <button className="dialog-close" onClick={onClose}><X size={18} /></button>
        </div>

        <div className="dialog-form">
          <div className="form-field">
            <label>بحث عن عضو</label>
            <div className="toolbar-search">
              <Search size={16} className="search-icon" />
              <input
                placeholder="ابحث بالاسم أو المعرّف..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
          </div>

          <div className="form-field">
            <label>اختيار العضو</label>
            <div className="members-list">
              {filteredAvailable.length ? (
                filteredAvailable.map((member) => (
                  <button
                    key={member.user_id}
                    type="button"
                    className={`member-option ${selectedUser === member.user_id ? 'selected' : ''}`}
                    onClick={() => setSelectedUser(member.user_id)}
                  >
                    <div className="member-avatar">{(member.full_name || 'U').slice(0, 1)}</div>
                    <div className="member-option__info">
                      <strong>{member.full_name || 'مستخدم بدون اسم'}</strong>
                      <span>{member.user_id}</span>
                    </div>
                  </button>
                ))
              ) : (
                <div className="dash-empty">لا يوجد أعضاء متاحين</div>
              )}
            </div>
          </div>

          <div className="form-field">
            <label>دور العضو في الفريق</label>
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as AddTeamMemberRequest['role'])}
              className="form-select"
            >
              <option value="lead">قائد (Lead)</option>
              <option value="member">عضو (Member)</option>
              <option value="viewer">مشاهد (Viewer)</option>
            </select>
          </div>

          <div className="dialog-actions">
            <button type="button" className="btn btn-ghost" onClick={onClose}>إلغاء</button>
            <button
              type="button"
              className="btn btn-primary"
              disabled={isLoading || !selectedUser}
              onClick={() => onSubmit({ user_id: selectedUser, role })}
            >
              {isLoading ? <><Loader2 size={16} className="spin" /> جاري الإضافة...</> : <><UserPlus size={16} /> إضافة للفريق</>}
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
export default function TeamsPage() {
  const currentTenantId = useAuthStore(s => s.currentTenantId)

  // Guard
  const hasAccess = usePermission(PERM.NAV_TEAMS)
  const currentTenant = useAuthStore(s => s.tenants.find(t => t.tenant_id === currentTenantId))
  const queryClient = useQueryClient()

  // ── State ──
  const [selectedTeam, setSelectedTeam] = useState<Team | null>(null)
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [editingTeam, setEditingTeam] = useState<Team | null>(null)
  const [deletingTeam, setDeletingTeam] = useState<Team | null>(null)
  const [archivingTeam, setArchivingTeam] = useState<Team | null>(null)
  const [showAddMemberDialog, setShowAddMemberDialog] = useState(false)
  const [removingMember, setRemovingMember] = useState<{ teamId: string; userId: string; name: string } | null>(null)
  const [expandedTeam, setExpandedTeam] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'archived'>('all')

  // ── Queries ──
  const teamsQuery = useQuery({
    queryKey: ['teams', currentTenantId],
    queryFn: teamsAPI.list,
    enabled: Boolean(currentTenantId) && hasAccess,
  })

  const membersQuery = useQuery({
    queryKey: ['team-members', expandedTeam],
    queryFn: () => teamsAPI.members(expandedTeam!),
    enabled: Boolean(expandedTeam) && hasAccess,
  })

  const allMembersQuery = useQuery({
    queryKey: ['users', currentTenantId],
    queryFn: usersAPI.list,
    enabled: Boolean(currentTenantId) && hasAccess,
  })

  const teams = useMemo(() => teamsQuery.data ?? [], [teamsQuery.data])
  const teamMembers = useMemo(() => membersQuery.data ?? [], [membersQuery.data])
  const allMembers = useMemo(() => allMembersQuery.data ?? [], [allMembersQuery.data])

  // ── Mutations ──
  const createMutation = useMutation({
    mutationFn: (data: CreateTeamRequest) => teamsAPI.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['teams', currentTenantId] })
      setShowCreateDialog(false)
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateTeamRequest }) =>
      teamsAPI.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['teams', currentTenantId] })
      setEditingTeam(null)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: teamsAPI.remove,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['teams', currentTenantId] })
      setDeletingTeam(null)
      if (selectedTeam?.id === deletingTeam?.id) setSelectedTeam(null)
    },
  })

  const archiveMutation = useMutation({
    mutationFn: ({ id, isActive }: { id: string; isActive: boolean }) =>
      isActive ? teamsAPI.activate(id) : teamsAPI.archive(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['teams', currentTenantId] })
      setArchivingTeam(null)
    },
  })

  const addMemberMutation = useMutation({
    mutationFn: ({ teamId, data }: { teamId: string; data: AddTeamMemberRequest }) =>
      teamsAPI.addMember(teamId, data),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['team-members', variables.teamId] })
      queryClient.invalidateQueries({ queryKey: ['dashboard', currentTenantId] })
      setShowAddMemberDialog(false)
    },
  })

  const removeMemberMutation = useMutation({
    mutationFn: ({ teamId, userId }: { teamId: string; userId: string }) =>
      teamsAPI.removeMember(teamId, userId),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['team-members', variables.teamId] })
      setRemovingMember(null)
    },
  })

  // ── Filtering ──
  const filteredTeams = useMemo(() => {
    return teams.filter((team) => {
      const matchesSearch = search
        ? team.name.toLowerCase().includes(search.toLowerCase()) ||
          team.description?.toLowerCase().includes(search.toLowerCase())
        : true

      const matchesStatus =
        statusFilter === 'all'
          ? true
          : statusFilter === 'active'
            ? team.is_active
            : !team.is_active

      return matchesSearch && matchesStatus
    })
  }, [teams, search, statusFilter])

  // ── Stats ──
  const stats = useMemo(
    () => ({
      total: teams.length,
      active: teams.filter((t) => t.is_active).length,
      archived: teams.filter((t) => !t.is_active).length,
      totalMembers: teams.reduce((acc, t) => acc + (t.member_count || 0), 0),
    }),
    [teams],
  )

  if (!hasAccess) {
    return <Navigate to="/dashboard" replace />
  }

  // ═══════════════════════════════════════════════════════
  // RENDER
  // ═══════════════════════════════════════════════════════
  return (
    <WorkspaceShell
      title="الفرق"
      subtitle={`${currentTenant?.name || 'مساحة العمل'} · تنظيم فرق التشغيل والتصميم والاستقبال`}
      actions={
        <div className="header-actions">
          <Can permission={PERM.TEAM_CREATE}>
            <button className="btn btn-primary" onClick={() => setShowCreateDialog(true)}>
              <Plus size={16} /> إنشاء فريق
            </button>
          </Can>
          <button className="dash-icon-btn" onClick={() => teamsQuery.refetch()} aria-label="تحديث">
            <RefreshCcw size={18} />
          </button>
        </div>
      }
    >
      {/* ── Stats ── */}
      <section className="dash-stats-grid teams-stats-grid">
        <div className="dash-stat">
          <div className="dash-stat__icon"><FolderKanban size={20} /></div>
          <div>
            <span className="dash-stat__label">إجمالي الفرق</span>
            <strong className="dash-stat__value">{stats.total}</strong>
            <span className="dash-stat__delta">{stats.active} نشط</span>
          </div>
        </div>
        <div className="dash-stat dash-stat--blue">
          <div className="dash-stat__icon"><Users size={20} /></div>
          <div>
            <span className="dash-stat__label">الأعضاء في الفرق</span>
            <strong className="dash-stat__value">{stats.totalMembers}</strong>
            <span className="dash-stat__delta">موزعين على الفرق</span>
          </div>
        </div>
        <div className="dash-stat dash-stat--gold">
          <div className="dash-stat__icon"><Shield size={20} /></div>
          <div>
            <span className="dash-stat__label">الفرق النشطة</span>
            <strong className="dash-stat__value">{stats.active}</strong>
            <span className="dash-stat__delta">{stats.archived} مؤرشف</span>
          </div>
        </div>
      </section>

      {/* ── Teams List ── */}
      <section className="dash-panel">
        <div className="dash-panel__head">
          <div>
            <span>الفرق</span>
            <h2>إدارة الفرق وتوزيع الأعضاء</h2>
          </div>
          <FolderKanban size={20} />
        </div>

        {/* Toolbar */}
        <div className="users-toolbar">
          <div className="toolbar-search">
            <Search size={16} className="search-icon" />
            <input
              className="users-search"
              placeholder="ابحث باسم الفريق..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          <div className="toolbar-filters">
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as typeof statusFilter)}
              className="filter-select"
            >
              <option value="all">جميع الفرق</option>
              <option value="active">نشط</option>
              <option value="archived">مؤرشف</option>
            </select>
          </div>
        </div>

        {/* Teams Grid */}
        {teamsQuery.isLoading ? <div className="dash-empty">جار تحميل الفرق...</div> : null}
        {teamsQuery.isError ? (
          <div className="dash-empty">
            <AlertCircle size={24} />
            <p>تعذر تحميل الفرق</p>
            <button className="btn btn-primary" onClick={() => teamsQuery.refetch()}>
              إعادة المحاولة
            </button>
          </div>
        ) : null}

        {!teamsQuery.isLoading && !teamsQuery.isError && (
          <div className="teams-grid">
            {filteredTeams.length ? (
              filteredTeams.map((team) => {
                const isExpanded = expandedTeam === team.id
                const isSelected = selectedTeam?.id === team.id

                return (
                  <motion.div
                    key={team.id}
                    className={`team-card-v2 ${isSelected ? 'team-card-v2--selected' : ''} ${!team.is_active ? 'team-card-v2--archived' : ''}`}
                    layout
                  >
                    {/* Card Header */}
                    <div className="team-card-v2__header" onClick={() => setSelectedTeam(team)}>
                      <div className="team-card-v2__color" style={{ background: team.color || '#D4A32C' }} />
                      <div className="team-card-v2__info">
                        <strong>{team.name}</strong>
                        <span>{team.description || 'لا يوجد وصف'}</span>
                      </div>
                      <span className={`team-status ${team.is_active ? 'active' : 'archived'}`}>
                        {team.is_active ? 'نشط' : 'مؤرشف'}
                      </span>
                    </div>

                    {/* Card Actions */}
                    <div className="team-card-v2__actions">
                      <Can permission={PERM.TEAM_MANAGE}>
                        <button
                          className="action-btn"
                          onClick={() => setEditingTeam(team)}
                          title="تعديل"
                        >
                          <Edit3 size={14} />
                        </button>
                      </Can>
                      <Can permission={PERM.TEAM_ARCHIVE}>
                        <button
                          className="action-btn"
                          onClick={() => setArchivingTeam(team)}
                          title={team.is_active ? 'أرشفة' : 'تفعيل'}
                        >
                          {team.is_active ? <Archive size={14} /> : <ArchiveRestore size={14} />}
                        </button>
                        <button
                          className="action-btn action-btn--danger"
                          onClick={() => setDeletingTeam(team)}
                          title="حذف"
                        >
                          <Trash2 size={14} />
                        </button>
                      </Can>
                      <button
                        className="action-btn"
                        onClick={() => setExpandedTeam(isExpanded ? null : team.id)}
                        title="عرض الأعضاء"
                      >
                        {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                      </button>
                    </div>

                    {/* Expanded Members */}
                    <AnimatePresence>
                      {isExpanded && (
                        <motion.div
                          className="team-card-v2__members"
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: 'auto', opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                        >
                          <div className="members-header">
                            <span>أعضاء الفريق</span>
                            <Can permission={PERM.TEAM_MANAGE}>
                              <button
                                className="btn btn-sm btn-primary"
                                onClick={() => {
                                  setSelectedTeam(team)
                                  setShowAddMemberDialog(true)
                                }}
                              >
                                <UserPlus size={14} /> إضافة
                              </button>
                            </Can>
                          </div>
                          <div className="members-mini-list">
                            {teamMembers.length ? (
                              teamMembers.map((member) => (
                                <div key={member.id} className="member-mini-row">
                                  <div className="member-avatar small">
                                    {(member.full_name || 'U').slice(0, 1)}
                                  </div>
                                  <div className="member-mini-info">
                                    <strong>{member.full_name || 'مستخدم'}</strong>
                                    <span>{teamRoleLabel[member.role]}</span>
                                  </div>
                                  <Can permission={PERM.TEAM_MANAGE}>
                                    <button
                                      className="action-btn action-btn--danger"
                                      onClick={() =>
                                        setRemovingMember({
                                          teamId: team.id,
                                          userId: member.user_id,
                                          name: member.full_name || 'مستخدم',
                                        })
                                      }
                                      title="إزالة"
                                    >
                                      <UserMinus size={12} />
                                    </button>
                                  </Can>
                                </div>
                              ))
                            ) : (
                              <div className="dash-empty">لا يوجد أعضاء</div>
                            )}
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </motion.div>
                )
              })
            ) : (
              <div className="dash-empty">
                {search || statusFilter !== 'all'
                  ? 'لا توجد فرق مطابقة للبحث'
                  : 'لا توجد فرق بعد'}
              </div>
            )}
          </div>
        )}
      </section>

      {/* ── Dialogs ── */}
      <AnimatePresence>
        {showCreateDialog && (
          <TeamDialog
            isOpen={showCreateDialog}
            onClose={() => setShowCreateDialog(false)}
            onSubmit={(data) => createMutation.mutate(data)}
            isLoading={createMutation.isPending}
          />
        )}

        {editingTeam && (
          <TeamDialog
            isOpen={!!editingTeam}
            onClose={() => setEditingTeam(null)}
            team={editingTeam}
            onSubmit={(data) =>
              updateMutation.mutate({ id: editingTeam.id, data })
            }
            isLoading={updateMutation.isPending}
          />
        )}

        {deletingTeam && (
          <ConfirmDeleteDialog
            isOpen={!!deletingTeam}
            onClose={() => setDeletingTeam(null)}
            onConfirm={() => deleteMutation.mutate(deletingTeam.id)}
            isLoading={deleteMutation.isPending}
            title="حذف الفريق"
            message={`هل أنت متأكد من حذف الفريق "${deletingTeam.name}"؟ لا يمكن التراجع عن هذا الإجراء.`}
          />
        )}

        {archivingTeam && (
          <ConfirmDeleteDialog
            isOpen={!!archivingTeam}
            onClose={() => setArchivingTeam(null)}
            onConfirm={() =>
              archiveMutation.mutate({
                id: archivingTeam.id,
                isActive: !archivingTeam.is_active,
              })
            }
            isLoading={archiveMutation.isPending}
            title={archivingTeam.is_active ? 'أرشفة الفريق' : 'تفعيل الفريق'}
            message={
              archivingTeam.is_active
                ? `هل أنت متأكد من أرشفة الفريق "${archivingTeam.name}"؟`
                : `هل أنت متأكد من إعادة تفعيل الفريق "${archivingTeam.name}"؟`
            }
          />
        )}

        {showAddMemberDialog && selectedTeam && (
          <AddTeamMemberDialog
            isOpen={showAddMemberDialog}
            onClose={() => setShowAddMemberDialog(false)}
            existingMembers={teamMembers}
            availableMembers={allMembers}
            onSubmit={(data) =>
              addMemberMutation.mutate({ teamId: selectedTeam.id, data })
            }
            isLoading={addMemberMutation.isPending}
          />
        )}

        {removingMember && (
          <ConfirmDeleteDialog
            isOpen={!!removingMember}
            onClose={() => setRemovingMember(null)}
            onConfirm={() =>
              removeMemberMutation.mutate({
                teamId: removingMember.teamId,
                userId: removingMember.userId,
              })
            }
            isLoading={removeMemberMutation.isPending}
            title="إزالة عضو"
            message={`هل أنت متأكد من إزالة "${removingMember.name}" من الفريق؟`}
          />
        )}
      </AnimatePresence>
    </WorkspaceShell>
  )
}
