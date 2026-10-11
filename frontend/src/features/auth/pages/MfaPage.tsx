import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { useQueryClient } from '@tanstack/react-query'
import { AlertCircle, Loader2, ShieldCheck } from 'lucide-react'
import { authAPI } from '../api/authApi'
import { useAuthStore } from '../store/authStore'
import type { MfaEnrollment } from '../types'
import { getApiErrorMessage } from '@services/http/client'
import './auth.css'

/**
 * GoTrue returns the QR either as a raw SVG document or as an un-encoded SVG
 * data URI, depending on version.  Normalise both to an encoded data URI.
 */
const qrSrc = (raw: string) => {
  const prefix = 'data:image/svg+xml;utf-8,'
  const svg = raw.startsWith(prefix) ? raw.slice(prefix.length) : raw
  return svg.trimStart().startsWith('<')
    ? `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
    : raw
}

type Phase = 'loading' | 'enroll' | 'verify' | 'failed'

export default function MfaPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const user = useAuthStore(s => s.user)
  const [phase, setPhase] = useState<Phase>('loading')
  const [factorId, setFactorId] = useState<string>('')
  const [enrollment, setEnrollment] = useState<MfaEnrollment | null>(null)
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const status = await authAPI.mfaStatus()
        if (cancelled) return
        if (status.enrolled && status.factor_id) {
          setFactorId(status.factor_id)
          setPhase('verify')
        } else {
          const e = await authAPI.mfaEnroll()
          if (cancelled) return
          setEnrollment(e)
          setFactorId(e.factor_id)
          setPhase('enroll')
        }
      } catch (err) {
        if (cancelled) return
        setError(getApiErrorMessage(err, 'تعذر تجهيز المصادقة الثنائية. حاول مرة أخرى.'))
        setPhase('failed')
      }
    })()
    return () => { cancelled = true }
  }, [])

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!/^\d{6}$/.test(code)) {
      setError('أدخل الرمز المكوّن من 6 أرقام')
      return
    }
    setBusy(true)
    setError('')
    try {
      await authAPI.mfaVerify(factorId, code)
      queryClient.clear()
      navigate(user?.is_staff ? '/platform' : '/dashboard', { replace: true })
    } catch (err) {
      setError(getApiErrorMessage(err, 'الرمز غير صحيح'))
      setCode('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-orb auth-orb--1" />
      <div className="auth-orb auth-orb--2" />
      <main className="auth-layout">
        <motion.div className="auth-card" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}>
          <div className="auth-logo"><img src="/logo.png" alt="Qentry" className="auth-logo__img" /></div>
          <div className="auth-header">
            <h1 className="auth-title">المصادقة الثنائية</h1>
            <p className="auth-subtitle">
              {phase === 'enroll'
                ? 'امسح الرمز بتطبيق المصادقة (Google Authenticator أو Microsoft Authenticator) ثم أدخل الرمز الظاهر فيه.'
                : 'أدخل الرمز المكوّن من 6 أرقام من تطبيق المصادقة.'}
            </p>
          </div>

          {phase === 'loading' && (
            <p className="auth-subtitle"><Loader2 size={18} className="spin" /> جاري التجهيز…</p>
          )}

          {phase === 'failed' && (
            <div className="auth-error"><AlertCircle size={16} /><span>{error}</span></div>
          )}

          {(phase === 'enroll' || phase === 'verify') && (
            <form onSubmit={submit} className="auth-form" noValidate>
              {phase === 'enroll' && enrollment && (
                <div className="field" style={{ textAlign: 'center' }}>
                  <img
                    src={qrSrc(enrollment.qr_code)}
                    alt="رمز QR للمصادقة الثنائية"
                    width={200}
                    height={200}
                    style={{ background: '#fff', padding: 8, borderRadius: 12, margin: '0 auto' }}
                  />
                  <p className="field__label" style={{ marginTop: 12 }}>أو أدخل هذا المفتاح يدوياً:</p>
                  <code dir="ltr" style={{ wordBreak: 'break-all', userSelect: 'all' }}>{enrollment.secret}</code>
                </div>
              )}

              {error && (
                <div className="auth-error"><AlertCircle size={16} /><span>{error}</span></div>
              )}

              <div className="field">
                <label className="field__label">رمز التحقق</label>
                <input
                  className="field__input"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={6}
                  placeholder="123456"
                  dir="ltr"
                  value={code}
                  onChange={e => setCode(e.target.value.replace(/\D/g, ''))}
                  autoFocus
                />
              </div>

              <button type="submit" className="auth-btn" disabled={busy || code.length !== 6}>
                {busy
                  ? <><Loader2 size={18} className="spin" /> جاري التحقق…</>
                  : <><ShieldCheck size={18} /> تحقق ومتابعة</>}
              </button>
            </form>
          )}
        </motion.div>
      </main>
    </div>
  )
}
