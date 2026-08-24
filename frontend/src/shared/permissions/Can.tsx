import type { ReactNode } from 'react'
import { usePermission, useAnyPermission } from './usePermission'
import type { PermissionKey } from './keys'

interface CanProps {
  permission?: PermissionKey | string
  anyOf?: (PermissionKey | string)[]
  children: ReactNode
  fallback?: ReactNode
}

/** Renders children only when the user has the required permission(s). */
export function Can({ permission, anyOf, children, fallback = null }: CanProps) {
  const hasSinglePermission = usePermission(permission ?? '')
  const hasAnyPermission = useAnyPermission(...(anyOf ?? []))
  const hasSingle = permission ? hasSinglePermission : true
  const hasAny = anyOf ? hasAnyPermission : true

  if (!hasSingle || !hasAny) return <>{fallback}</>
  return <>{children}</>
}
