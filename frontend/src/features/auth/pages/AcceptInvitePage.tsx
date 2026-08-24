import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { CheckCircle2, Loader2, ShieldCheck, AlertCircle } from 'lucide-react'
import http from '@services/http/client'
import { useAuthStore } from '../store/authStore'
import './auth.css'

export default function AcceptInvitePage() {
  const { token = '' } = useParams<{ token: string }>()
  const navigate = useNavigate()
  const isAuthenticated = useAuthStore(s => s.isAuthenticated)
  const [state, setState] = useState<'waiting' | 'loading' | 'success' | 'error'>('waiting')
  const [message, setMessage] = useState('')

  useEffect(() => {
    if (!token || !isAuthenticated || state !== 'waiting') return
    setState('loading')
    http.post(`/invites/accept/${encodeURIComponent(token)}`)
      .then(() => {
        setState('success')
        setMessage('تم قبول الدعوة وإضافتك إلى المؤسسة بنجاح.')
      })
      .catch((err) => {
        setState('error')
        setMessage(err?.response?.data?.detail || 'تعذر قبول الدعوة. قد تكون منتهية أو ملغاة.')
      })
  }, [token, isAuthenticated, state])

  if (!isAuthenticated) {
    const loginUrl = `/auth/login?invite=${encodeURIComponent(token)}`
    return <InviteShell icon={<ShieldCheck size={34} />} title="دعوة للانضمام">
      <p>سجّل الدخول بالحساب الذي استلم الدعوة، ثم سنكمل الانضمام تلقائيًا.</p>
      <Link className="auth-btn" to={loginUrl}>تسجيل الدخول والمتابعة</Link>
      <Link className="auth-footer__link" to="/auth/signup">ليس لديك حساب؟ إنشاء حساب</Link>
    </InviteShell>
  }

  return <InviteShell icon={state === 'error' ? <AlertCircle size={34} /> : state === 'success' ? <CheckCircle2 size={34} /> : <Loader2 size={34} className="spin" />} title={state === 'error' ? 'تعذر قبول الدعوة' : state === 'success' ? 'تم الانضمام بنجاح' : 'جاري قبول الدعوة'}>
    <p>{state === 'loading' ? 'لحظات من فضلك...' : message}</p>
    {state === 'success' && <button className="auth-btn" onClick={() => navigate('/dashboard', { replace: true })}>الانتقال إلى لوحة التحكم</button>}
    {state === 'error' && <button className="auth-btn" onClick={() => window.location.reload()}>المحاولة مرة أخرى</button>}
  </InviteShell>
}

function InviteShell({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return <div className="auth-page"><div className="auth-card" style={{ textAlign: 'center' }}><div className="auth-logo">{icon}</div><h1 className="auth-title">{title}</h1><div className="auth-form">{children}</div></div></div>
}
