import { useState, useRef, useEffect, useCallback } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { KeyRound, Loader2, AlertCircle, ShieldCheck, Send, ArrowRight } from 'lucide-react'
import { authAPI } from '../api/authApi'
import { useAuthStore } from '../store/authStore'
import type { AuthUser } from '../types'
import './auth.css'

export default function VerifySignupPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const email = searchParams.get('email') || ''
  const setAuth = useAuthStore(s => s.setAuth)

  const [otpValues, setOtpValues] = useState<string[]>(Array(6).fill(''))
  const [otpLoading, setOtpLoading] = useState(false)
  const [serverError, setServerError] = useState('')
  const [resendTimer, setResendTimer] = useState(60)
  const [canResend, setCanResend] = useState(false)
  const [resendMsg, setResendMsg] = useState('')
  const inputRefs = useRef<(HTMLInputElement | null)[]>([])

  useEffect(() => {
    if (canResend) return
    const timer = setInterval(() => {
      setResendTimer(prev => {
        if (prev <= 1) {
          setCanResend(true)
          clearInterval(timer)
          return 0
        }
        return prev - 1
      })
    }, 1000)
    return () => clearInterval(timer)
  }, [canResend])

  const handleOtpChange = (index: number, value: string) => {
    if (!/^\d*$/.test(value)) return
    const newValues = [...otpValues]
    newValues[index] = value.slice(-1)
    setOtpValues(newValues)
    if (value && index < 5) inputRefs.current[index + 1]?.focus()
  }

  const handleOtpKeyDown = (index: number, e: React.KeyboardEvent) => {
    if (e.key === 'Backspace' && !otpValues[index] && index > 0) {
      inputRefs.current[index - 1]?.focus()
    }
  }

  const handleOtpPaste = (e: React.ClipboardEvent) => {
    e.preventDefault()
    const pasted = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6)
    const newValues = [...otpValues]
    for (let i = 0; i < 6; i++) newValues[i] = pasted[i] || ''
    setOtpValues(newValues)
    inputRefs.current[Math.min(pasted.length, 5)]?.focus()
  }

  const onVerify = useCallback(async () => {
    const code = otpValues.join('')
    if (code.length !== 6 || !email) return

    setOtpLoading(true)
    setServerError('')
    try {
      const res = await authAPI.verifySignupOtp({ email, otp_code: code })

      let profile
      try { profile = await authAPI.me() } catch (err) { console.error('Failed to fetch user profile', err) }

      const user: AuthUser = {
        id:         profile?.user_id || res.user_id!,
        email:      profile?.email || email,
        full_name:  profile?.full_name || null,
        avatar_url: profile?.avatar_url || null,
        is_staff:   profile?.is_staff || false,
      }
      const tenants = res.tenants || profile?.tenants || []
      setAuth(user, tenants, tenants[0]?.tenant_id, profile?.permissions || [])
      navigate('/dashboard', { replace: true })
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } }
      setServerError(e?.response?.data?.detail || 'رمز التحقق غير صحيح أو منتهي الصلاحية')
      setOtpValues(Array(6).fill(''))
      inputRefs.current[0]?.focus()
    } finally {
      setOtpLoading(false)
    }
  }, [otpValues, email, navigate, setAuth])

  useEffect(() => {
    if (otpValues.every(v => v !== '')) onVerify()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [otpValues])

  const onResend = async () => {
    setServerError('')
    setResendMsg('')
    setCanResend(false)
    setResendTimer(60)
    try {
      await authAPI.resendSignupOtp({ email })
      setResendMsg('تم إرسال رمز جديد إلى بريدك.')
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } }
      setServerError(e?.response?.data?.detail || 'فشل إعادة الإرسال')
    }
  }

  if (!email) {
    return (
      <div className="auth-page">
        <div className="auth-orb auth-orb--1" />
        <div className="auth-orb auth-orb--2" />
        <motion.div className="auth-card" initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }}>
          <div className="auth-header">
            <h1 className="auth-title">رابط غير صالح</h1>
            <p className="auth-subtitle">لا يوجد بريد إلكتروني لتأكيده. ابدأ عملية التسجيل من جديد.</p>
          </div>
          <div className="auth-footer">
            <Link to="/auth/signup" className="auth-footer__link">إنشاء حساب</Link>
          </div>
        </motion.div>
      </div>
    )
  }

  return (
    <div className="auth-page">
      <div className="auth-orb auth-orb--1" />
      <div className="auth-orb auth-orb--2" />

      <motion.div
        className="auth-card"
        initial={{ opacity: 0, y: 24, scale: 0.97 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.5, ease: [0.34, 1.56, 0.64, 1] }}
      >
        <div className="auth-logo">
          <img src="/logo.png" alt="Qentry" className="auth-logo__img" />
        </div>

        <AnimatePresence mode="wait">
          <motion.div key="otp" initial={{ opacity: 0, x: 40 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.3 }}>
            <div className="auth-header">
              <div className="forgot-icon-wrap">
                <KeyRound size={28} strokeWidth={1.5} />
              </div>
              <h1 className="auth-title">تأكيد حسابك</h1>
              <p className="auth-subtitle">تم إرسال رمز مكون من 6 أرقام إلى</p>
              <div className="forgot-email-badge">{email}</div>
            </div>

            <div className="auth-form">
              {serverError && (
                <motion.div className="auth-error" initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }}>
                  <AlertCircle size={16} />
                  <span>{serverError}</span>
                </motion.div>
              )}

              <div className="otp-inputs" onPaste={handleOtpPaste}>
                {otpValues.map((val, i) => (
                  <input
                    key={i}
                    ref={el => { inputRefs.current[i] = el }}
                    type="text"
                    inputMode="numeric"
                    maxLength={1}
                    value={val}
                    onChange={e => handleOtpChange(i, e.target.value)}
                    onKeyDown={e => handleOtpKeyDown(i, e)}
                    className={`otp-input ${val ? 'otp-input--filled' : ''}`}
                    autoFocus={i === 0}
                    dir="ltr"
                  />
                ))}
              </div>

              {otpLoading && (
                <div className="otp-verifying">
                  <Loader2 size={18} className="spin" />
                  <span>جاري التحقق...</span>
                </div>
              )}

              <div className="otp-resend">
                {canResend ? (
                  <button type="button" className="otp-resend__btn" onClick={onResend}>
                    <Send size={14} />
                    إعادة إرسال الرمز
                  </button>
                ) : (
                  <span className="otp-resend__timer">
                    إعادة الإرسال بعد <strong>{resendTimer}</strong> ثانية
                  </span>
                )}
              </div>
              {resendMsg && <p className="auth-subtitle" style={{ textAlign: 'center' }}>{resendMsg}</p>}

              <button
                type="button"
                className="auth-btn"
                disabled={otpLoading || otpValues.some(v => !v)}
                onClick={onVerify}
              >
                {otpLoading ? (
                  <><Loader2 size={18} className="spin" /> جاري التحقق...</>
                ) : (
                  <><ShieldCheck size={18} /> تأكيد الحساب</>
                )}
              </button>
            </div>

            <div className="auth-footer">
              <Link to="/auth/signup" className="auth-back-link">
                <ArrowRight size={16} />
                العودة لإنشاء الحساب
              </Link>
            </div>
          </motion.div>
        </AnimatePresence>
      </motion.div>
    </div>
  )
}
