import { useState } from 'react'
import { Bell, CheckCheck } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { notificationsAPI } from '../api/notificationsApi'
import './notifications.css'

export function NotificationCenter() {
  const [open, setOpen] = useState(false)
  const qc = useQueryClient(); const navigate = useNavigate()
  const count = useQuery({ queryKey:['notifications-count'], queryFn:notificationsAPI.unreadCount, refetchInterval:30000 })
  const list = useQuery({ queryKey:['notifications'], queryFn:notificationsAPI.list, enabled:open })
  const read = useMutation({ mutationFn:notificationsAPI.read, onSuccess:()=>qc.invalidateQueries({queryKey:['notifications']}) })
  const all = useMutation({ mutationFn:notificationsAPI.readAll, onSuccess:()=>{ qc.invalidateQueries({queryKey:['notifications']}); qc.invalidateQueries({queryKey:['notifications-count']}) } })
  return <div className="notification-center">
    <button className="notification-bell" onClick={()=>setOpen(v=>!v)} aria-label="الإشعارات"><Bell size={20}/>{!!count.data?.count && <b>{count.data.count}</b>}</button>
    {open && <div className="notification-panel">
      <div className="notification-panel__head"><strong>الإشعارات</strong><button onClick={()=>all.mutate()}><CheckCheck size={15}/> قراءة الكل</button></div>
      <div className="notification-list">{list.data?.map(n=><button key={n.id} className={n.read_at?'':'unread'} onClick={()=>{ if(!n.read_at) read.mutate(n.id); if(n.link){setOpen(false);navigate(n.link)} }}><strong>{n.title}</strong><span>{n.message}</span><small>{new Date(n.created_at).toLocaleString('ar')}</small></button>)}
      {!list.isLoading && !list.data?.length && <p>لا توجد إشعارات.</p>}</div>
    </div>}
  </div>
}
