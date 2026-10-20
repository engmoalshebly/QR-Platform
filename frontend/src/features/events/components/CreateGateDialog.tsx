import { LimitErrorNotice } from '@components/LimitErrorNotice'
import { useState, useEffect, useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, DoorOpen, Loader2, CheckSquare, Square, Search, Users, User } from 'lucide-react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useQuery } from '@tanstack/react-query'
import { teamsAPI } from '@features/teams/api/teamsApi'
import { usersAPI } from '@features/users/api/usersApi'
import { useAuthStore } from '@features/auth/store/authStore'
import { useGateCreate, useGateUpdate } from '../hooks/useEventDetails'
import type { EventGate, TicketClass } from '../types'

const schema = z.object({
  name: z.string().min(2, 'الاسم يجب أن يكون حرفين على الأقل'),
})

type FormData = z.infer<typeof schema>

interface Props {
  eventId: string
  isOpen: boolean
  onClose: () => void
  gate?: EventGate | null
}

export function CreateGateDialog({ eventId, isOpen, onClose, gate }: Props) {
  const isEditing = !!gate
  const [serverError, setServerError] = useState<unknown>(null)
  
  // States
  const [allowedClasses, setAllowedClasses] = useState<TicketClass[]>(['normal', 'vip'])
  const [selectedTeamId, setSelectedTeamId] = useState<string>('')
  const [selectedUserIds, setSelectedUserIds] = useState<string[]>([])
  const [userSearch, setUserSearch] = useState('')

  const currentTenantId = useAuthStore((s) => s.currentTenantId)

  // React hook form
  const {
    register,
    handleSubmit,
    reset,
    setValue,
    formState: { errors },
  } = useForm<FormData>({
    resolver: zodResolver(schema),
  })

  // Set initial values if editing
  useEffect(() => {
    if (gate) {
      setValue('name', gate.name)
      setAllowedClasses(gate.allowed_classes || [])
      setSelectedTeamId(gate.team_id || '')
      setSelectedUserIds(gate.assigned_users || [])
    } else {
      reset({ name: '' })
      setAllowedClasses(['normal', 'vip'])
      setSelectedTeamId('')
      setSelectedUserIds([])
    }
    setServerError('')
    setUserSearch('')
  }, [gate, setValue, reset])

  // Queries
  const { data: teams = [], isLoading: isLoadingTeams } = useQuery({
    queryKey: ['teams', currentTenantId],
    queryFn: teamsAPI.list,
    enabled: Boolean(isOpen && currentTenantId),
  })

  const { data: users = [], isLoading: isLoadingUsers } = useQuery({
    queryKey: ['users', currentTenantId],
    queryFn: usersAPI.list,
    enabled: Boolean(isOpen && currentTenantId),
  })

  // Mutations
  const createMutation = useGateCreate(eventId)
  const updateMutation = useGateUpdate(eventId)

  const isPending = createMutation.isPending || updateMutation.isPending

  const toggleClass = (tc: TicketClass) => {
    setAllowedClasses(prev => 
      prev.includes(tc) ? prev.filter(c => c !== tc) : [...prev, tc]
    )
  }

  // Filter users based on search query
  const filteredUsers = useMemo(() => {
    return users.filter(user => 
      user.full_name?.toLowerCase().includes(userSearch.toLowerCase()) ||
      user.user_id.toLowerCase().includes(userSearch.toLowerCase())
    )
  }, [users, userSearch])

  const onSubmit = (data: FormData) => {
    if (allowedClasses.length === 0) {
      setServerError('يجب تحديد فئة تذاكر واحدة على الأقل')
      return
    }
    setServerError('')

    const payload = {
      name: data.name,
      allowed_classes: allowedClasses,
      team_id: selectedTeamId || null,
      assigned_users: selectedUserIds,
    }

    if (isEditing && gate) {
      updateMutation.mutate(
        { gateId: gate.id, data: payload },
        {
          onSuccess: () => {
            onClose()
          },
          onError: (err: any) => {
            setServerError(err)
          }
        }
      )
    } else {
      createMutation.mutate(payload, {
        onSuccess: () => {
          onClose()
        },
        onError: (err: any) => {
          setServerError(err)
        }
      })
    }
  }

  if (!isOpen) return null

  return (
    <AnimatePresence>
      <div className="dialog-overlay" onClick={onClose}>
        <motion.div
          className="dialog-content"
          initial={{ opacity: 0, scale: 0.95, y: 10 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 10 }}
          onClick={e => e.stopPropagation()}
          style={{ maxWidth: '520px', width: '100%' }}
        >
          <div className="dialog-header">
            <h3>{isEditing ? 'تعديل بوابة الدخول' : 'إنشاء بوابة دخول'}</h3>
            <button className="dialog-close" onClick={onClose}>
              <X size={20} />
            </button>
          </div>

          <form onSubmit={handleSubmit(onSubmit)} className="dialog-form" noValidate>
            <LimitErrorNotice error={serverError} onRetry={handleSubmit(onSubmit)} />

            {/* Gate Name */}
            <div className="form-field">
              <label>اسم البوابة</label>
              <input
                {...register('name')}
                type="text"
                placeholder="مثال: البوابة الشرقية (VIP)"
                className={errors.name ? 'error' : ''}
                disabled={isPending}
              />
              {errors.name && <span className="form-error">{errors.name.message}</span>}
            </div>

            {/* Allowed Classes */}
            <div className="form-field">
              <label>الفئات المسموح لها بالدخول</label>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 6 }}>
                <label className="toggle-row" style={{ cursor: 'pointer', padding: '10px 14px', margin: 0, border: '1px solid rgba(255,255,255,0.05)', borderRadius: '8px' }}>
                  <div className="toggle-row-info">
                    <h4 style={{ color: '#D4A32C', fontSize: '13px', margin: 0 }}>كبار الشخصيات (VIP)</h4>
                    <p style={{ fontSize: '11px', opacity: 0.6, margin: '2px 0 0 0' }}>أصحاب تذاكر ودعوات الـ VIP فقط</p>
                  </div>
                  <button type="button" className="checkbox-btn" onClick={() => toggleClass('vip')} disabled={isPending}>
                    {allowedClasses.includes('vip') ? <CheckSquare size={20} color="#D4A32C" /> : <Square size={20} />}
                  </button>
                </label>
                
                <label className="toggle-row" style={{ cursor: 'pointer', padding: '10px 14px', margin: 0, border: '1px solid rgba(255,255,255,0.05)', borderRadius: '8px' }}>
                  <div className="toggle-row-info">
                    <h4 style={{ fontSize: '13px', margin: 0 }}>الضيوف العاديين (Normal)</h4>
                    <p style={{ fontSize: '11px', opacity: 0.6, margin: '2px 0 0 0' }}>التذاكر العادية المخصصة للجمهور</p>
                  </div>
                  <button type="button" className="checkbox-btn" onClick={() => toggleClass('normal')} disabled={isPending}>
                    {allowedClasses.includes('normal') ? <CheckSquare size={20} /> : <Square size={20} />}
                  </button>
                </label>
              </div>
            </div>

            {/* Operating Team Selection */}
            <div className="form-field">
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Users size={14} style={{ color: 'var(--color-primary)' }} />
                إسناد فريق تشغيل للبوابة
              </label>
              {isLoadingTeams ? (
                <div style={{ fontSize: '12px', opacity: 0.5 }}>جاري تحميل الفرق...</div>
              ) : (
                <select 
                  value={selectedTeamId} 
                  onChange={e => setSelectedTeamId(e.target.value)}
                  className="form-select"
                  disabled={isPending}
                  style={{ width: '100%', padding: '10px', borderRadius: '8px', border: '1px solid var(--color-border)', background: 'var(--color-bg-surface)', color: 'var(--color-text)' }}
                >
                  <option value="">لا يوجد فريق (متاحة لجميع المنظمين)</option>
                  {teams.filter(t => t.is_active).map(team => (
                    <option key={team.id} value={team.id}>
                      {team.name}
                    </option>
                  ))}
                </select>
              )}
              <p className="form-field-hint" style={{ fontSize: '11px', opacity: 0.5, marginTop: 4, lineHeight: '1.4' }}>
                عند إسناد فريق، سيتمكن أعضاء هذا الفريق فقط من القيام بالمسح وتسجيل الحضور عند هذه البوابة.
              </p>
            </div>

            {/* Specific Users Checklist */}
            <div className="form-field">
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <User size={14} style={{ color: 'var(--color-primary)' }} />
                تحديد أشخاص محددين للعمل على البوابة (بالإضافة للفريق إن وُجد)
              </label>
              
              <div className="toolbar-search" style={{ marginBottom: 8, height: '36px' }}>
                <Search size={14} className="search-icon" />
                <input
                  type="text"
                  placeholder="بحث باسم المنظم..."
                  value={userSearch}
                  onChange={e => setUserSearch(e.target.value)}
                  disabled={isPending}
                  style={{ fontSize: '12px' }}
                />
              </div>

              {isLoadingUsers ? (
                <div style={{ fontSize: '12px', opacity: 0.5 }}>جاري تحميل المنظمين...</div>
              ) : (
                <div style={{ 
                  maxHeight: '140px', 
                  overflowY: 'auto', 
                  border: '1px solid var(--color-border)', 
                  borderRadius: '8px',
                  padding: '6px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '4px',
                  background: 'rgba(255,255,255,0.01)'
                }}>
                  {filteredUsers.length > 0 ? (
                    filteredUsers.map(user => {
                      const isChecked = selectedUserIds.includes(user.user_id)
                      return (
                        <label 
                          key={user.user_id} 
                          style={{ 
                            display: 'flex', 
                            alignItems: 'center', 
                            justifyContent: 'space-between',
                            padding: '6px 8px', 
                            borderRadius: '6px',
                            background: isChecked ? 'rgba(212,163,44,0.06)' : 'transparent',
                            cursor: 'pointer',
                            margin: 0
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <div className="member-avatar small" style={{ width: 22, height: 22, fontSize: '10px', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--color-primary-light)', color: '#000', fontWeight: 'bold' }}>
                              {(user.full_name || 'U').slice(0, 1)}
                            </div>
                            <span style={{ fontSize: '12px', color: isChecked ? 'var(--color-primary)' : 'inherit' }}>
                              {user.full_name || 'مستخدم بدون اسم'}
                            </span>
                          </div>
                          <input
                            type="checkbox"
                            checked={isChecked}
                            onChange={() => {
                              setSelectedUserIds(prev => 
                                prev.includes(user.user_id) 
                                  ? prev.filter(uid => uid !== user.user_id) 
                                  : [...prev, user.user_id]
                              )
                            }}
                            disabled={isPending}
                            style={{ cursor: 'pointer' }}
                          />
                        </label>
                      )
                    })
                  ) : (
                    <div style={{ fontSize: '11px', color: 'rgba(255,255,255,0.4)', textAlign: 'center', padding: '12px 0' }}>
                      لا يوجد أعضاء مطابقين للبحث
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Footer Actions */}
            <div className="dialog-actions" style={{ marginTop: 24 }}>
              <button type="button" className="btn btn-ghost" onClick={onClose} disabled={isPending}>
                إلغاء
              </button>
              <button type="submit" className="btn btn-primary" disabled={isPending}>
                {isPending ? <><Loader2 size={16} className="spin" /> جاري الحفظ...</> : <><DoorOpen size={16} /> {isEditing ? 'حفظ التعديلات' : 'إضافة البوابة'}</>}
              </button>
            </div>
          </form>
        </motion.div>
      </div>
    </AnimatePresence>
  )
}
