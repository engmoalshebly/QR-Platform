import { getApiErrorMessage } from '@services/http/client'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { CheckCircle2, Loader2, ShieldCheck, AlertCircle, Eye, EyeOff } from 'lucide-react'
import http from '@services/http/client'
import { useAuthStore } from '../store/authStore'
import './auth.css'

type InviteCredentials = { email: string; initial_password: string }

export default function AcceptInvitePage() {
  const { token = '' } = useParams<{ token: string }>()
  const navigate = useNavigate()
  const isAuthenticated = useAuthStore(s => s.isAuthenticated)
  const [state, setState] = useState<'waiting' | 'loading' | 'success' | 'error'>('waiting')
  const [message, setMessage] = useState('')
  const [credentials, setCredentials] = useState<InviteCredentials | null>(null)
  const [showPassword, setShowPassword] = useState(false)
  const [existingEmail, setExistingEmail] = useState('')
  const [alreadyAccepted, setAlreadyAccepted] = useState(false)

  useEffect(() => {
    if (!token || !isAuthenticated || state !== 'waiting') return
    setState('loading')
    http.post(`/invites/accept/${encodeURIComponent(token)}`)
      .then(() => {
        setState('success')
        setMessage('تم قبول الدعوة وإضافتك إلى مساحة العمل بنجاح.')
      })
      .catch((err) => {
        setState('error')
        setMessage(getApiErrorMessage(err, 'تعذر قبول الدعوة. قد تكون منتهية أو ملغاة.'))
      })
  }, [token, isAuthenticated, state])

  const activateAccount = async () => {
    if (state === 'loading') return
    setState('loading')
    setMessage('')
    try {
      const { data } = await http.post<InviteCredentials>(`/invites/accept/${encodeURIComponent(token)}/activate`)
      // Credentials stay in memory only; reopening the link never retrieves
      // them or changes an existing account's password.
      setCredentials(data)
      setState('success')
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: { code?: string; email?: string } } } }).response?.data?.detail
      if (detail?.code === 'INVITE_ACCOUNT_EXISTS' || detail?.code === 'INVITE_ALREADY_ACCEPTED') {
        setExistingEmail(detail.email || '')
        setAlreadyAccepted(detail.code === 'INVITE_ALREADY_ACCEPTED')
      }
      setMessage(getApiErrorMessage(err, 'تعذر إنشاء الحساب وقبول الدعوة. حاول لاحقاً.'))
      setState('error')
    }
  }

  if (credentials) {
    return <InviteShell icon={<CheckCircle2 size={34} />} title="تم إنشاء حسابك والانضمام">
      <p>حسابك جاهز. احفظ بيانات الدخول قبل مغادرة الصفحة؛ كلمة المرور تظهر هنا مرة واحدة.</p>
      <div className="field">
        <label className="field__label" htmlFor="invite-email">البريد الإلكتروني</label>
        <input id="invite-email" className="field__input" dir="ltr" readOnly value={credentials.email} />
      </div>
      <div className="field">
        <label className="field__label" htmlFor="invite-password">كلمة المرور الأولية</label>
        <input id="invite-password" className="field__input" dir="ltr" type={showPassword ? 'text' : 'password'}
          readOnly value={credentials.initial_password} autoComplete="off" />
        <button type="button" className="auth-footer__link" onClick={() => setShowPassword(value => !value)}>
          {showPassword ? <EyeOff size={16} /> : <Eye size={16} />} {showPassword ? 'إخفاء كلمة المرور' : 'إظهار كلمة المرور'}
        </button>
      </div>
      <Link className="auth-btn" to={`/auth/login?email=${encodeURIComponent(credentials.email)}`}>تسجيل الدخول بحسابي</Link>
      <p>يمكنك تغيير كلمة المرور لاحقاً عبر «نسيت كلمة المرور».</p>
    </InviteShell>
  }

  if (!isAuthenticated) {
    const loginParams = new URLSearchParams()
    if (!alreadyAccepted) loginParams.set('invite', token)
    if (existingEmail) loginParams.set('email', existingEmail)
    return <InviteShell icon={<ShieldCheck size={34} />} title="دعوة للانضمام">
      <p>اقبل الدعوة لننشئ حسابك ونمنحك كلمة مرور أولية تلقائياً. ستنضم إلى مساحة الفريق مباشرة.</p>
      {message && <p role="alert">{message}</p>}
      {!existingEmail && <button className="auth-btn" onClick={activateAccount} disabled={state === 'loading'}>
        {state === 'loading' ? <><Loader2 size={18} className="spin" /> جار إنشاء حسابك...</> : 'قبول الدعوة وإنشاء حسابي'}
      </button>}
      <Link className="auth-footer__link" to={`/auth/login?${loginParams}`}>لدي حساب بالفعل — تسجيل الدخول</Link>
      {existingEmail && <Link className="auth-footer__link" to="/auth/forgot-password">نسيت كلمة المرور</Link>}
    </InviteShell>
  }

  return <InviteShell icon={state === 'error' ? <AlertCircle size={34} /> : state === 'success' ? <CheckCircle2 size={34} /> : <Loader2 size={34} className="spin" />} title={state === 'error' ? 'تعذر قبول الدعوة' : state === 'success' ? 'تم الانضمام بنجاح' : 'جاري قبول الدعوة'}>
    <p>{state === 'loading' ? 'لحظات من فضلك...' : message}</p>
    {state === 'success' && <button className="auth-btn" onClick={() => navigate('/', { replace: true })}>الانتقال إلى مساحة العمل</button>}
    {state === 'error' && <button className="auth-btn" onClick={() => window.location.reload()}>المحاولة مرة أخرى</button>}
  </InviteShell>
}

function InviteShell({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return <div className="auth-page"><div className="auth-card" style={{ textAlign: 'center' }}><div className="auth-logo">{icon}</div><h1 className="auth-title">{title}</h1><div className="auth-form">{children}</div></div></div>
}
