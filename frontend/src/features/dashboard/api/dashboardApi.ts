import http from '@services/http/client'
import type { DashboardAnalytics } from '../types'

export const dashboardAPI = {
  analytics: async (): Promise<DashboardAnalytics> => {
    const { data } = await http.get<DashboardAnalytics>('/dashboard/analytics')
    return data
  },
  provider: async (): Promise<any> => {
    const { data } = await http.get<any>('/dashboard/provider')
    return data
  },
}
