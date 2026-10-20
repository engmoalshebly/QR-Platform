/**
 * EventGatesTab.tsx
 * Gates management tab — upgraded to display assigned teams and specific users,
 * and support Editing gates with team/user assignments.
 */
import { useState } from 'react'
import { DoorOpen, Loader2, Trash2, Edit3, ShieldCheck, Users } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { useEventGates, useGateDelete } from '../hooks/useEventDetails'
import { CreateGateDialog } from './CreateGateDialog'
import { ConfirmDialog } from './ConfirmDialog'
import { formatDateShort } from '../utils/eventUtils'
import { teamsAPI } from '@features/teams/api/teamsApi'
import { usersAPI } from '@features/users/api/usersApi'
import { useAuthStore } from '@features/auth/store/authStore'
import type { EventGate } from '../types'
import { Can, PERM } from '@shared/permissions'

interface Props {
  eventId: string
  isActiveTab: boolean
}

export function EventGatesTab({ eventId, isActiveTab }: Props) {
  const [showCreate, setShowCreate] = useState(false)
  const [editTarget, setEditTarget] = useState<EventGate | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null)

  const currentTenantId = useAuthStore((s) => s.currentTenantId)

  // Queries
  const { data: gates, isLoading } = useEventGates(eventId, isActiveTab)
  const deleteMutation = useGateDelete(eventId)

  const { data: teams = [] } = useQuery({
    queryKey: ['teams', currentTenantId],
    queryFn: teamsAPI.list,
    enabled: Boolean(isActiveTab && currentTenantId),
  })

  const { data: users = [] } = useQuery({
    queryKey: ['users', currentTenantId],
    queryFn: usersAPI.list,
    enabled: Boolean(isActiveTab && currentTenantId),
  })

  const handleConfirmDelete = () => {
    if (!deleteTarget) return
    deleteMutation.mutate(deleteTarget.id, {
      onSuccess: () => setDeleteTarget(null),
    })
  }

  return (
    <div className="event-form-section">
      {/* ── Header ── */}
      <div className="event-section-header">
        <h3 className="section-title">
          <DoorOpen size={18} />
          بوابات الدخول للحدث
        </h3>
        <Can permission={PERM.GATES_CREATE}>
          <button className="btn btn-primary btn-sm" onClick={() => setShowCreate(true)}>
            <DoorOpen size={14} />
            إضافة بوابة
          </button>
        </Can>
      </div>

      {/* ── Content ── */}
      {isLoading ? (
        <div className="center-loader">
          <Loader2 size={28} className="spin" />
          <span>جاري التحميل…</span>
        </div>
      ) : !gates?.length ? (
        <div className="gates-empty-state">
          <ShieldCheck size={40} />
          <p>لا توجد بوابات مخصصة</p>
          <span>سيتم استخدام البوابة الرئيسية افتراضياً لجميع الضيوف.</span>
        </div>
      ) : (
        <div className="gates-list">
          {/* Header row */}
          <div className="gates-list__head" style={{ gridTemplateColumns: '1.8fr 1.2fr 1.2fr 1.2fr 1fr 1fr' }}>
            <div>اسم البوابة</div>
            <div>الفئات المسموح لها</div>
            <div>فريق التشغيل</div>
            <div>أشخاص مخصصين</div>
            <div>تاريخ الإنشاء</div>
            <div style={{ textAlign: 'center' }}>إجراءات</div>
          </div>

          {/* Data rows */}
          {gates.map((gate) => {
            const assignedTeam = teams.find(t => t.id === gate.team_id)
            const assignedUsers = users.filter(u => gate.assigned_users?.includes(u.user_id))

            return (
              <div key={gate.id} className="gates-list__row" style={{ gridTemplateColumns: '1.8fr 1.2fr 1.2fr 1.2fr 1fr 1fr', alignItems: 'center' }}>
                {/* Gate Name */}
                <div className="gates-list__name">
                  <DoorOpen size={14} style={{ color: 'var(--color-primary-light)', flexShrink: 0 }} />
                  <strong>{gate.name}</strong>
                  {gate.name_ar && <span className="gates-list__name-ar">{gate.name_ar}</span>}
                </div>

                {/* Ticket Classes */}
                <div className="gates-list__classes">
                  {gate.allowed_classes?.map((c) => (
                    <span
                      key={c}
                      className={`users-chip ${c === 'vip' ? 'users-chip--owner' : 'users-chip--member'}`}
                      style={{ fontSize: '11px', padding: '2px 6px' }}
                    >
                      {c === 'vip' ? '👑 VIP' : '🎫 عادي'}
                    </span>
                  ))}
                </div>

                {/* Assigned Team */}
                <div>
                  {assignedTeam ? (
                    <span 
                      className="users-chip"
                      style={{ 
                        fontSize: '11px', 
                        padding: '2px 8px',
                        background: (assignedTeam.color || '#D4A32C') + '12',
                        color: assignedTeam.color || '#D4A32C',
                        border: `1px solid ${assignedTeam.color || '#D4A32C'}30`
                      }}
                    >
                      <Users size={10} style={{ display: 'inline', marginLeft: 4, verticalAlign: 'middle' }} />
                      {assignedTeam.name}
                    </span>
                  ) : (
                    <span style={{ opacity: 0.35, fontSize: '12px' }}>متاح لجميع المنظمين</span>
                  )}
                </div>

                {/* Assigned Users Avatars */}
                <div>
                  {assignedUsers.length > 0 ? (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <div style={{ display: 'flex', direction: 'ltr' }}>
                        {assignedUsers.slice(0, 3).map((user, idx) => (
                          <div 
                            key={user.user_id}
                            className="member-avatar small" 
                            style={{ 
                              width: 22, 
                              height: 22, 
                              fontSize: '9px',
                              marginLeft: idx > 0 ? '-6px' : '0',
                              border: '2px solid var(--color-bg-surface)',
                              position: 'relative',
                              zIndex: 3 - idx,
                              borderRadius: '50%',
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              background: 'var(--color-primary-light)',
                              color: '#000',
                              fontWeight: 'bold'
                            }}
                            title={user.full_name || 'منظم'}
                          >
                            {(user.full_name || 'U').slice(0, 1)}
                          </div>
                        ))}
                      </div>
                      {assignedUsers.length > 3 && (
                        <span style={{ fontSize: '11px', opacity: 0.5 }}>+{assignedUsers.length - 3}</span>
                      )}
                    </div>
                  ) : (
                    <span style={{ opacity: 0.35, fontSize: '12px' }}>لا يوجد</span>
                  )}
                </div>

                {/* Created At */}
                <div className="date-cell">{formatDateShort(gate.created_at)}</div>

                {/* Actions */}
                <div style={{ textAlign: 'center', display: 'flex', justifyContent: 'center', gap: '8px' }}>
                  <Can permission={PERM.GATES_EDIT}>
                    <button
                      className="action-btn"
                      onClick={() => setEditTarget(gate)}
                      title="تعديل البوابة"
                    >
                      <Edit3 size={15} />
                    </button>
                  </Can>
                  <Can permission={PERM.GATES_DELETE}>
                    <button
                      className="action-btn action-btn--danger"
                      onClick={() => setDeleteTarget({ id: gate.id, name: gate.name })}
                      title="حذف البوابة"
                    >
                      <Trash2 size={15} />
                    </button>
                  </Can>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* ── Dialogs ── */}
      {(showCreate || editTarget) && (
        <CreateGateDialog
          eventId={eventId}
          isOpen={showCreate || !!editTarget}
          gate={editTarget}
          onClose={() => {
            setShowCreate(false)
            setEditTarget(null)
          }}
        />
      )}

      <ConfirmDialog
        isOpen={Boolean(deleteTarget)}
        title="حذف البوابة"
        message={`هل أنت متأكد من حذف بوابة "${deleteTarget?.name}"؟ لا يمكن التراجع عن هذا الإجراء.`}
        confirmLabel="نعم، احذف"
        variant="danger"
        isPending={deleteMutation.isPending}
        onConfirm={handleConfirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  )
}
