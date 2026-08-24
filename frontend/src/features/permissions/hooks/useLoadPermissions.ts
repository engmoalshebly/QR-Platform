import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAuthStore } from '@features/auth/store/authStore'
import { authAPI } from '@features/auth/api/authApi'

/** Reload user info and permissions periodically. Call once in WorkspaceShell. */
export function useLoadPermissions() {
  const tenantId = useAuthStore(s => s.currentTenantId)
  const userId = useAuthStore(s => s.user?.id)
  const isAuthenticated = useAuthStore(s => s.isAuthenticated)

  const { data: meInfo, error } = useQuery({
    queryKey: ['my-profile-and-permissions', userId, tenantId],
    queryFn: () => authAPI.me(),
    enabled: Boolean(isAuthenticated && userId && tenantId),
    refetchInterval: 3000, // Poll every 3 seconds for near-instant updates!
    refetchOnWindowFocus: true,
    retry: false,
  })

  useEffect(() => {
    if (meInfo) {
      useAuthStore.setState({
        user: {
          id: meInfo.id || meInfo.user_id || '',
          email: meInfo.email,
          full_name: meInfo.full_name,
          avatar_url: meInfo.avatar_url,
          is_staff: meInfo.is_staff,
        },
        tenants: meInfo.tenants || [],
        permissions: new Set(meInfo.permissions || []),
      })
    } else if (error) {
      useAuthStore.setState({
        permissions: new Set(),
      })
    }
  }, [meInfo, error])
}
