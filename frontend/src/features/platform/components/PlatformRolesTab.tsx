import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Shield, Loader2, Save, Plus, Trash2, Building2 } from 'lucide-react'
import { platformAPI } from '../api/platformApi'
import type { PlatformTenant } from '../api/platformApi'
import { PERMISSION_GROUPS, PERMISSION_LABELS_AR } from '@shared/permissions'
import '@features/settings/pages/roles.css'

export function PlatformRolesTab() {
  const qc = useQueryClient()
  const [tenantId, setTenantId] = useState<string>('')
  const [workspaceScope, setWorkspaceScope] = useState<'organizer' | 'institution'>('organizer')
  const [selectedRoleId, setSelectedRoleId] = useState<string | null>(null)
  const [draftPerms, setDraftPerms] = useState<Set<string>>(new Set())
  const [newRoleName, setNewRoleName] = useState('')
  const [msg, setMsg] = useState('')

  const { data: tenants = [], isLoading: tenantsLoading } = useQuery({
    queryKey: ['platform-tenants-roles'],
    queryFn: () => platformAPI.listTenants({ limit: 200 }),
  })

  const { data: allPermissions = [] } = useQuery({
    queryKey: ['platform-permissions'],
    queryFn: platformAPI.listPermissions,
  })
  const groupedPermissionKeys = new Set<string>(PERMISSION_GROUPS.flatMap(group => group.keys))
  const additionalPermissions = allPermissions.filter(permission => !groupedPermissionKeys.has(permission.key))

  useEffect(() => {
    if (!tenantId && tenants.length > 0) {
      setTenantId(tenants[0]!.id)
    }
  }, [tenants, tenantId])

  useEffect(() => {
    setSelectedRoleId(null)
    setDraftPerms(new Set())
    setMsg('')
    setWorkspaceScope('organizer')
  }, [tenantId])

  const selectedTenant = tenants.find((t: PlatformTenant) => t.id === tenantId)
  const activeTenantId = workspaceScope === 'institution' && selectedTenant?.linked_tenant_id
    ? selectedTenant.linked_tenant_id
    : tenantId

  useEffect(() => {
    setSelectedRoleId(null)
    setDraftPerms(new Set())
    setMsg('')
  }, [activeTenantId])

  const { data: roles, isLoading: rolesLoading } = useQuery({
    queryKey: ['platform-roles', activeTenantId],
    queryFn: () => platformAPI.listTenantRoles(activeTenantId),
    enabled: !!activeTenantId,
  })

  const selectedRole = roles?.find(r => r.id === selectedRoleId)

  const saveMutation = useMutation({
    mutationFn: () =>
      platformAPI.updateTenantRole(activeTenantId, selectedRoleId!, { permissions: Array.from(draftPerms) }),
    onSuccess: () => {
      setMsg('تم حفظ الصلاحيات بنجاح')
      qc.invalidateQueries({ queryKey: ['platform-roles', activeTenantId] })
    },
    onError: () => setMsg('فشل حفظ الصلاحيات'),
  })

  const createMutation = useMutation({
    mutationFn: () =>
      platformAPI.createTenantRole(activeTenantId, { name: newRoleName.trim(), permissions: [] }),
    onSuccess: (role) => {
      setNewRoleName('')
      qc.invalidateQueries({ queryKey: ['platform-roles', activeTenantId] })
      setSelectedRoleId(role.id)
      setDraftPerms(new Set())
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => platformAPI.deleteTenantRole(activeTenantId, id),
    onSuccess: () => {
      setSelectedRoleId(null)
      qc.invalidateQueries({ queryKey: ['platform-roles', activeTenantId] })
    },
  })

  const selectRole = (id: string) => {
    const role = roles?.find(r => r.id === id)
    setSelectedRoleId(id)
    setDraftPerms(new Set(role?.permissions || []))
    setMsg('')
  }

  const togglePerm = (key: string) => {
    setDraftPerms(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  return (
    <div className="plat-tab-content">
      <div className="plat-toolbar plat-toolbar--roles">
        <div className="plat-tenant-picker">
          <Building2 size={16} />
          <label htmlFor="plat-tenant-select">المؤسسة:</label>
          <select
            id="plat-tenant-select"
            value={tenantId}
            onChange={e => setTenantId(e.target.value)}
            disabled={tenantsLoading}
          >
            {tenants.map((t: PlatformTenant) => (
              <option key={t.id} value={t.id}>
                [{t.workspace_type === 'organizer' ? 'فريق تنظيم' : 'مؤسسة'}] {t.name} ({t.slug})
              </option>
            ))}
          </select>
        </div>
        {selectedTenant && (
          <span className="plat-tenant-hint">
            إدارة صلاحيات المؤسسة الموحّدة: <strong>{selectedTenant.name}</strong>
          </span>
        )}
        {selectedTenant?.linked_tenant_id && (
          <div className="plat-workspace-scope" role="group" aria-label="نطاق الصلاحيات">
            <button type="button" className={workspaceScope === 'organizer' ? 'active' : ''} onClick={() => setWorkspaceScope('organizer')}>فريق التشغيل</button>
            <button type="button" className={workspaceScope === 'institution' ? 'active' : ''} onClick={() => setWorkspaceScope('institution')}>المؤسسة والفعاليات</button>
          </div>
        )}
      </div>

      {!activeTenantId ? (
        <div className="plat-loading">اختر مؤسسة لإدارة أدوارها</div>
      ) : (
        <div className="roles-layout roles-layout--platform">
          <aside className="roles-sidebar">
            <h3>الأدوار</h3>
            {rolesLoading ? <Loader2 className="spin" /> : (
              <ul className="roles-list">
                {roles?.map(role => (
                  <li key={role.id}>
                    <button
                      type="button"
                      className={`roles-list__item${selectedRoleId === role.id ? ' roles-list__item--active' : ''}`}
                      onClick={() => selectRole(role.id)}
                    >
                      <Shield size={14} />
                      {role.name}
                      {role.is_system_role && <span className="roles-badge">نظام</span>}
                    </button>
                  </li>
                ))}
              </ul>
            )}

            <div className="roles-create">
              <input
                value={newRoleName}
                onChange={e => setNewRoleName(e.target.value)}
                placeholder="اسم دور جديد"
              />
              <button
                type="button"
                className="settings-btn"
                disabled={!newRoleName.trim() || createMutation.isPending}
                onClick={() => createMutation.mutate()}
              >
                <Plus size={14} /> إضافة
              </button>
            </div>
          </aside>

          <section className="roles-matrix">
            {!selectedRole ? (
              <p className="roles-hint">اختر دوراً لتعديل صلاحياته لهذه المؤسسة</p>
            ) : (
              <>
                <div className="roles-matrix__header">
                  <h2>{selectedRole.name}</h2>
                  <div className="roles-matrix__actions">
                    <button
                      type="button"
                      className="settings-btn"
                      disabled={saveMutation.isPending}
                      onClick={() => saveMutation.mutate()}
                    >
                      {saveMutation.isPending ? <Loader2 size={14} className="spin" /> : <Save size={14} />}
                      حفظ الصلاحيات
                    </button>
                    {!selectedRole.is_system_role && (
                      <button
                        type="button"
                        className="settings-btn"
                        style={{ borderColor: 'rgba(239,68,68,0.4)', color: '#fca5a5' }}
                        onClick={() => deleteMutation.mutate(selectedRole.id)}
                      >
                        <Trash2 size={14} /> حذف الدور
                      </button>
                    )}
                  </div>
                </div>

                {msg && <div className="settings-msg settings-msg--success">{msg}</div>}

                {PERMISSION_GROUPS.map(group => (
                  <div key={group.label} className="roles-group">
                    <h4>{group.label}</h4>
                    <div className="roles-checks">
                      {group.keys.map(key => (
                        <label key={key} className="roles-check">
                          <input
                            type="checkbox"
                            checked={draftPerms.has(key)}
                            onChange={() => togglePerm(key)}
                          />
                          <span>{PERMISSION_LABELS_AR[key] || key}</span>
                          <code>{key}</code>
                        </label>
                      ))}
                    </div>
                  </div>
                ))}
                {additionalPermissions.length > 0 && (
                  <div className="roles-group">
                    <h4>صلاحيات النظام الإضافية</h4>
                    <div className="roles-checks">
                      {additionalPermissions.map(permission => (
                        <label key={permission.key} className="roles-check">
                          <input
                            type="checkbox"
                            checked={draftPerms.has(permission.key)}
                            onChange={() => togglePerm(permission.key)}
                          />
                          <span>{permission.description || permission.key}</span>
                          <code>{permission.key}</code>
                        </label>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </section>
        </div>
      )}
    </div>
  )
}
