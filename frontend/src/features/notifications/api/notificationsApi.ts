import http from '@services/http/client'

export interface AppNotification { id:string; type:string; title:string; message:string; link?:string; read_at?:string; created_at:string }

export const notificationsAPI = {
  list: async () => (await http.get<AppNotification[]>('/notifications')).data,
  unreadCount: async () => (await http.get<{count:number}>('/notifications/unread-count')).data,
  read: async (id:string) => http.post(`/notifications/${id}/read`),
  readAll: async () => http.post('/notifications/read-all'),
}
