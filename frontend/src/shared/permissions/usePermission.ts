import { useAuthStore } from '@features/auth/store/authStore'
import type { PermissionKey } from './keys'

function checkPermission(
  permissions: Set<string> | undefined,
  key: string,
  membershipRole?: string,
): boolean {
  if (membershipRole === 'owner') return true
  if (permissions && typeof permissions.has === 'function' && permissions.has(key)) return true
  return false
}

export function usePermissions(): Set<string> {
  const permissions = useAuthStore(s => s.permissions)
  return permissions instanceof Set ? permissions : new Set(permissions || [])
}

export function usePermission(key: PermissionKey | string): boolean {
  const permissions = useAuthStore(s => s.permissions)
  const currentTenantId = useAuthStore(s => s.currentTenantId)
  const tenants = useAuthStore(s => s.tenants) || []
  const role = tenants.find(t => t?.tenant_id === currentTenantId)?.role
  return checkPermission(permissions, key, role)
}

export function useAnyPermission(...keys: (PermissionKey | string)[]): boolean {
  const permissions = useAuthStore(s => s.permissions)
  const currentTenantId = useAuthStore(s => s.currentTenantId)
  const tenants = useAuthStore(s => s.tenants) || []
  const role = tenants.find(t => t?.tenant_id === currentTenantId)?.role
  return keys.some(k => checkPermission(permissions, k, role))
}

export function useAllPermissions(...keys: (PermissionKey | string)[]): boolean {
  const permissions = useAuthStore(s => s.permissions)
  const currentTenantId = useAuthStore(s => s.currentTenantId)
  const tenants = useAuthStore(s => s.tenants) || []
  const role = tenants.find(t => t?.tenant_id === currentTenantId)?.role
  return keys.every(k => checkPermission(permissions, k, role))
}
