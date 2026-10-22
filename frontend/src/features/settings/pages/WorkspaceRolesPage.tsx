import { useMemo, useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Plus, Save, Shield, Trash2 } from 'lucide-react'
import { WorkspaceShell } from '@features/workspace/components/WorkspaceShell'
import { PERM, PERMISSION_GROUPS, PERMISSION_LABELS_AR, usePermission } from '@shared/permissions'
import { permissionsAPI } from '@features/permissions/api/permissionsApi'
import '@features/settings/pages/roles.css'

/** Local role administration for the active institution or organizer workspace. */
export default function WorkspaceRolesPage() {
  const queryClient = useQueryClient()
  const canManageRoles = usePermission(PERM.ROLES_MANAGE)
  const [selectedRoleId, setSelectedRoleId] = useState<string | null>(null)
  const [draftPermissions, setDraftPermissions] = useState<Set<string>>(new Set())
  const [roleName, setRoleName] = useState('')
  const [message, setMessage] = useState('')

  const rolesQuery = useQuery({
    queryKey: ['workspace-roles'],
    queryFn: permissionsAPI.listRoles,
    enabled: canManageRoles,
  })
  const permissionsQuery = useQuery({
    queryKey: ['workspace-permissions'],
    queryFn: permissionsAPI.listAllPermissions,
    enabled: canManageRoles,
  })

  const selectedRole = rolesQuery.data?.find(role => role.id === selectedRoleId)
  const groups = useMemo(() => {
    const listed = new Set<string>(PERMISSION_GROUPS.flatMap(group => group.keys))
    const remaining = (permissionsQuery.data || []).filter(permission => !listed.has(permission.key))
    return [
      ...PERMISSION_GROUPS,
      ...(remaining.length ? [{ label: 'صلاحيات النظام الإضافية', keys: remaining.map(permission => permission.key) }] : []),
    ]
  }, [permissionsQuery.data])

  const selectRole = (roleId: string) => {
    const role = rolesQuery.data?.find(item => item.id === roleId)
    setSelectedRoleId(roleId)
    setDraftPermissions(new Set(role?.permissions || []))
    setMessage('')
  }

  const saveRole = useMutation({
    mutationFn: () => permissionsAPI.updateRole(selectedRoleId!, { permissions: [...draftPermissions] }),
    onSuccess: () => {
      setMessage('تم حفظ الصلاحيات بنجاح')
      queryClient.invalidateQueries({ queryKey: ['workspace-roles'] })
    },
    onError: () => setMessage('تعذر حفظ الصلاحيات'),
  })
  const createRole = useMutation({
    mutationFn: () => permissionsAPI.createRole({ name: roleName.trim(), permissions: [] }),
    onSuccess: role => {
      setRoleName('')
      queryClient.invalidateQueries({ queryKey: ['workspace-roles'] })
      setSelectedRoleId(role.id)
      setDraftPermissions(new Set())
    },
  })
  const deleteRole = useMutation({
    mutationFn: (roleId: string) => permissionsAPI.deleteRole(roleId),
    onSuccess: () => {
      setSelectedRoleId(null)
      setDraftPermissions(new Set())
      queryClient.invalidateQueries({ queryKey: ['workspace-roles'] })
    },
  })

  if (!canManageRoles) return <Navigate to="/settings" replace />

  const togglePermission = (key: string) => {
    setDraftPermissions(current => {
      const next = new Set(current)
      if (next.has(key)) {
        next.delete(key)
      } else {
        next.add(key)
      }
      return next
    })
  }

  return (
    <WorkspaceShell
      title="الأدوار والصلاحيات"
      subtitle="إدارة الوصول داخل مساحة العمل الحالية فقط"
      actions={<Link className="operation-back" to="/dashboard">العودة للرئيسية</Link>}
    >
      <div className="roles-layout" style={{ minHeight: 560 }}>
        <aside className="roles-sidebar">
          <h3>الأدوار</h3>
          {rolesQuery.isLoading ? <Loader2 className="spin" /> : (
            <ul className="roles-list">
              {rolesQuery.data?.map(role => (
                <li key={role.id}>
                  <button
                    type="button"
                    className={`roles-list__item${selectedRoleId === role.id ? ' roles-list__item--active' : ''}`}
                    onClick={() => selectRole(role.id)}
                  >
                    <Shield size={14} /> {role.name}
                    {role.is_system_role && <span className="roles-badge">نظام</span>}
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="roles-create">
            <input value={roleName} onChange={event => setRoleName(event.target.value)} placeholder="اسم دور جديد" />
            <button type="button" className="settings-btn" disabled={!roleName.trim() || createRole.isPending} onClick={() => createRole.mutate()}>
              <Plus size={14} /> إضافة
            </button>
          </div>
        </aside>

        <section className="roles-matrix">
          {!selectedRole ? <p className="roles-hint">اختر دوراً لعرض صلاحياته وتعديلها.</p> : (
            <>
              <div className="roles-matrix__header">
                <div><h2>{selectedRole.name}</h2><p>الصلاحيات تنطبق على هذه المؤسسة أو هذا الفريق فقط.</p></div>
                <div className="roles-matrix__actions">
                  <button type="button" className="settings-btn" disabled={saveRole.isPending} onClick={() => saveRole.mutate()}>
                    {saveRole.isPending ? <Loader2 size={14} className="spin" /> : <Save size={14} />} حفظ الصلاحيات
                  </button>
                  {!selectedRole.is_system_role && (
                    <button type="button" className="settings-btn" onClick={() => deleteRole.mutate(selectedRole.id)}>
                      <Trash2 size={14} /> حذف الدور
                    </button>
                  )}
                </div>
              </div>
              {message && <div className="settings-msg settings-msg--success">{message}</div>}
              {groups.map(group => (
                <div key={group.label} className="roles-group">
                  <h4>{group.label}</h4>
                  <div className="roles-checks">
                    {group.keys.map(key => (
                      <label key={key} className="roles-check">
                        <input type="checkbox" checked={draftPermissions.has(key)} onChange={() => togglePermission(key)} />
                        <span>{PERMISSION_LABELS_AR[key] || permissionsQuery.data?.find(item => item.key === key)?.description || key}</span>
                        <code>{key}</code>
                      </label>
                    ))}
                  </div>
                </div>
              ))}
            </>
          )}
        </section>
      </div>
    </WorkspaceShell>
  )
}
