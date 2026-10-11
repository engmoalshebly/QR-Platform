import { getApiErrorMessage } from '@services/http/client'
import { useState, useRef, useEffect, useCallback } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Mail, ArrowRight, Loader2, AlertCircle, CheckCircle2,
  Send, ShieldCheck, Eye, EyeOff, KeyRound, Lock, LogIn,
} from 'lucide-react'
import { authAPI } from '../api/authApi'
import './auth.css'

/* ── Schemas ── */
const emailSchema = z.object({
  email: z.string().email('بريد إلكتروني غير صالح'),
})
type EmailForm = z.infer<typeof emailSchema>

const passwordSchema = z.object({
  new_password: z
    .string()
    .min(12, 'كلمة المرور يجب أن تكون 12 حرفًا على الأقل')
    .regex(/[a-z]/, 'يجب أن تحتوي على حرف صغير')
    .regex(/[A-Z]/, 'يجب أن تحتوي على حرف كبير')
    .regex(/[0-9]/, 'يجب أن تحتوي على رقم'),
  confirm_password: z.string(),
}).refine((d) => d.new_password === d.confirm_password, {
  message: 'كلمات المرور غير متطابقة',
  path: ['confirm_password'],
})
type PasswordForm = z.infer<typeof passwordSchema>

const passwordRules = [
  { label: '12 حرفًا على الأقل', test: (p: string) => p.length >= 12 },
  { label: 'حرف صغير (a-z)',    test: (p: string) => /[a-z]/.test(p) },
  { label: 'حرف كبير (A-Z)',    test: (p: string) => /[A-Z]/.test(p) },
  { label: 'رقم (0-9)',         test: (p: string) => /[0-9]/.test(p) },
]

type Step = 'email' | 'otp' | 'password' | 'done'

/* ── Animations ── */
const stepVariants = {
  enter:  { opacity: 0, x: 40 },
  center: { opacity: 1, x: 0 },
  exit:   { opacity: 0, x: -40 },
}

export default function ForgotPasswordPage() {
  const navigate = useNavigate()
  const [step, setStep]               = useState<Step>('email')
  const [email, setEmail]             = useState('')
  const [resetToken, setResetToken]   = useState('')
  const [serverError, setServerError] = useState('')
  const [showNew, setShowNew]         = useState(false)
  const [showCnf, setShowCnf]        = useState(false)

  /* ── OTP State ── */
  const [otpValues, setOtpValues]     = useState<string[]>(Array(6).fill(''))
  const [otpLoading, setOtpLoading]   = useState(false)
  const [resendTimer, setResendTimer] = useState(60)
  const [canResend, setCanResend]     = useState(false)
  const inputRefs = useRef<(HTMLInputElement | null)[]>([])

  /* ── Step 1: Email Form ── */
  const emailForm = useForm<EmailForm>({ resolver: zodResolver(emailSchema) })

  const onEmailSubmit = async (data: EmailForm) => {
    setServerError('')
    try {
      await authAPI.sendOtp({ email: data.email })
      setEmail(data.email)
      setStep('otp')
      setResendTimer(60)
      setCanResend(false)
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } }
      setServerError(getApiErrorMessage(e, 'حدث خطأ، حاول مرة أخرى'))
    }
  }

  /* ── Resend Timer ── */
  useEffect(() => {
    if (step !== 'otp' || canResend) return
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
  }, [step, canResend])

  /* ── OTP Input Handlers ── */
  const handleOtpChange = (index: number, value: string) => {
    if (!/^\d*$/.test(value)) return
    const newValues = [...otpValues]
    newValues[index] = value.slice(-1)
    setOtpValues(newValues)

    // Auto-focus next input
    if (value && index < 5) {
      inputRefs.current[index + 1]?.focus()
    }
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
    for (let i = 0; i < 6; i++) {
      newValues[i] = pasted[i] || ''
    }
    setOtpValues(newValues)
    // Focus last filled input or the next empty one
    const lastIndex = Math.min(pasted.length, 5)
    inputRefs.current[lastIndex]?.focus()
  }

  /* ── Step 2: Verify OTP ── */
  const onVerifyOtp = useCallback(async () => {
    const code = otpValues.join('')
    if (code.length !== 6) return

    setOtpLoading(true)
    setServerError('')
    try {
      const res = await authAPI.verifyOtp({ email, otp_code: code })
      if (res.reset_token) {
        setResetToken(res.reset_token)
        setStep('password')
      }
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } }
      setServerError(getApiErrorMessage(e, 'رمز التحقق غير صحيح'))
      setOtpValues(Array(6).fill(''))
      inputRefs.current[0]?.focus()
    } finally {
      setOtpLoading(false)
    }
  }, [otpValues, email])

  // Auto-submit when 6 digits filled
  useEffect(() => {
    if (otpValues.every(v => v !== '') && step === 'otp') {
      onVerifyOtp()
    }
  }, [otpValues, step, onVerifyOtp])

  /* ── Resend OTP ── */
  const onResend = async () => {
    setServerError('')
    setCanResend(false)
    setResendTimer(60)
    try {
      await authAPI.sendOtp({ email })
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } }
      setServerError(getApiErrorMessage(e, 'فشل إعادة الإرسال'))
    }
  }

  /* ── Step 3: Password Form ── */
  const passwordForm = useForm<PasswordForm>({ resolver: zodResolver(passwordSchema) })
  const passwordValue = passwordForm.watch('new_password', '')

  const onPasswordSubmit = async (data: PasswordForm) => {
    setServerError('')
    try {
      await authAPI.confirmNewPassword({
        reset_token: resetToken,
        new_password: data.new_password,
      })
      setStep('done')
      setTimeout(() => navigate('/auth/login'), 3000)
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } }
      setServerError(getApiErrorMessage(e, 'فشل تغيير كلمة المرور'))
    }
  }

  /* ── Progress Steps ── */
  const steps: { key: Step; icon: typeof Mail; label: string }[] = [
    { key: 'email',    icon: Mail,        label: 'البريد' },
    { key: 'otp',      icon: KeyRound,    label: 'التحقق' },
    { key: 'password', icon: Lock,        label: 'كلمة المرور' },
  ]
  const stepIndex = step === 'done' ? 3 : steps.findIndex(s => s.key === step)

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
        {/* Logo */}
        <div className="auth-logo">
          <img src="/logo.png" alt="Da3wa" className="auth-logo__img" />
        </div>

        {/* Progress Steps */}
        {step !== 'done' && (
          <div className="otp-progress">
            {steps.map((s, i) => {
              const Icon = s.icon
              const isActive = i === stepIndex
              const isDone = i < stepIndex
              return (
                <div key={s.key} className="otp-progress__step">
                  <div
                    className={`otp-progress__circle ${isActive ? 'otp-progress__circle--active' : ''} ${isDone ? 'otp-progress__circle--done' : ''}`}
                  >
                    {isDone ? <CheckCircle2 size={16} /> : <Icon size={16} />}
                  </div>
                  <span className={`otp-progress__label ${isActive || isDone ? 'otp-progress__label--active' : ''}`}>
                    {s.label}
                  </span>
                  {i < steps.length - 1 && (
                    <div className={`otp-progress__line ${isDone ? 'otp-progress__line--done' : ''}`} />
                  )}
                </div>
              )
            })}
          </div>
        )}

        <AnimatePresence mode="wait">
          {/* ═══════ STEP 1: EMAIL ═══════ */}
          {step === 'email' && (
            <motion.div key="email" variants={stepVariants} initial="enter" animate="center" exit="exit" transition={{ duration: 0.3 }}>
              <div className="auth-header">
                <div className="forgot-icon-wrap">
                  <Mail size={28} strokeWidth={1.5} />
                </div>
                <h1 className="auth-title">استعادة كلمة المرور</h1>
                <p className="auth-subtitle">أدخل بريدك الإلكتروني وسنرسل لك رمز تحقق</p>
              </div>

              <form onSubmit={emailForm.handleSubmit(onEmailSubmit)} className="auth-form" noValidate>
                {serverError && (
                  <motion.div className="auth-error" initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }}>
                    <AlertCircle size={16} />
                    <span>{serverError}</span>
                  </motion.div>
                )}

                <div className="field">
                  <label className="field__label">البريد الإلكتروني</label>
                  <input
                    {...emailForm.register('email')}
                    type="email"
                    className={`field__input ${emailForm.formState.errors.email ? 'field__input--error' : ''}`}
                    placeholder="you@example.com"
                    autoComplete="email"
                    dir="ltr"
                    autoFocus
                  />
                  {emailForm.formState.errors.email && (
                    <span className="field__error">{emailForm.formState.errors.email.message}</span>
                  )}
                </div>

                <button type="submit" className="auth-btn" disabled={emailForm.formState.isSubmitting}>
                  {emailForm.formState.isSubmitting ? (
                    <><Loader2 size={18} className="spin" /> جاري التحقق...</>
                  ) : (
                    <><Send size={18} /> إرسال رمز التحقق</>
                  )}
                </button>
              </form>

              <div className="auth-footer">
                <Link to="/auth/login" className="auth-back-link">
                  <ArrowRight size={16} />
                  العودة لتسجيل الدخول
                </Link>
              </div>
            </motion.div>
          )}

          {/* ═══════ STEP 2: OTP ═══════ */}
          {step === 'otp' && (
            <motion.div key="otp" variants={stepVariants} initial="enter" animate="center" exit="exit" transition={{ duration: 0.3 }}>
              <div className="auth-header">
                <div className="forgot-icon-wrap">
                  <KeyRound size={28} strokeWidth={1.5} />
                </div>
                <h1 className="auth-title">إدخال رمز التحقق</h1>
                <p className="auth-subtitle">
                  تم إرسال رمز مكون من 6 أرقام إلى
                </p>
                <div className="forgot-email-badge">{email}</div>
              </div>

              <div className="auth-form">
                {serverError && (
                  <motion.div className="auth-error" initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }}>
                    <AlertCircle size={16} />
                    <span>{serverError}</span>
                  </motion.div>
                )}

                {/* OTP Inputs */}
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

                {/* Loading indicator */}
                {otpLoading && (
                  <div className="otp-verifying">
                    <Loader2 size={18} className="spin" />
                    <span>جاري التحقق...</span>
                  </div>
                )}

                {/* Resend Timer */}
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

                {/* Verify Button */}
                <button
                  type="button"
                  className="auth-btn"
                  disabled={otpLoading || otpValues.some(v => !v)}
                  onClick={onVerifyOtp}
                >
                  {otpLoading ? (
                    <><Loader2 size={18} className="spin" /> جاري التحقق...</>
                  ) : (
                    <><ShieldCheck size={18} /> تحقق من الرمز</>
                  )}
                </button>
              </div>

              <div className="auth-footer">
                <button
                  type="button"
                  className="auth-back-link"
                  onClick={() => { setStep('email'); setServerError(''); setOtpValues(Array(6).fill('')) }}
                  style={{ background: 'none', border: 'none', cursor: 'pointer' }}
                >
                  <ArrowRight size={16} />
                  تغيير البريد الإلكتروني
                </button>
              </div>
            </motion.div>
          )}

          {/* ═══════ STEP 3: NEW PASSWORD ═══════ */}
          {step === 'password' && (
            <motion.div key="password" variants={stepVariants} initial="enter" animate="center" exit="exit" transition={{ duration: 0.3 }}>
              <div className="auth-header">
                <div className="forgot-icon-wrap">
                  <ShieldCheck size={28} strokeWidth={1.5} />
                </div>
                <h1 className="auth-title">تعيين كلمة مرور جديدة</h1>
                <p className="auth-subtitle">أدخل كلمة مرور قوية لحماية حسابك</p>
              </div>

              <form onSubmit={passwordForm.handleSubmit(onPasswordSubmit)} className="auth-form" noValidate>
                {serverError && (
                  <motion.div className="auth-error" initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }}>
                    <AlertCircle size={16} />
                    <span>{serverError}</span>
                  </motion.div>
                )}

                {/* New Password */}
                <div className="field">
                  <label className="field__label">كلمة المرور الجديدة</label>
                  <div className="field__input-wrapper">
                    <input
                      {...passwordForm.register('new_password')}
                      type={showNew ? 'text' : 'password'}
                      className={`field__input field__input--padded ${passwordForm.formState.errors.new_password ? 'field__input--error' : ''}`}
                      placeholder="••••••••"
                      dir="ltr"
                      autoFocus
                    />
                    <button type="button" className="field__eye" onClick={() => setShowNew(v => !v)} tabIndex={-1}>
                      {showNew ? <EyeOff size={18} /> : <Eye size={18} />}
                    </button>
                  </div>
                  {passwordValue && (
                    <div className="password-rules">
                      {passwordRules.map(r => (
                        <div key={r.label} className={`password-rule ${r.test(passwordValue) ? 'password-rule--ok' : ''}`}>
                          <CheckCircle2 size={13} />
                          <span>{r.label}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {passwordForm.formState.errors.new_password && (
                    <span className="field__error">{passwordForm.formState.errors.new_password.message}</span>
                  )}
                </div>

                {/* Confirm Password */}
                <div className="field">
                  <label className="field__label">تأكيد كلمة المرور</label>
                  <div className="field__input-wrapper">
                    <input
                      {...passwordForm.register('confirm_password')}
                      type={showCnf ? 'text' : 'password'}
                      className={`field__input field__input--padded ${passwordForm.formState.errors.confirm_password ? 'field__input--error' : ''}`}
                      placeholder="••••••••"
                      dir="ltr"
                    />
                    <button type="button" className="field__eye" onClick={() => setShowCnf(v => !v)} tabIndex={-1}>
                      {showCnf ? <EyeOff size={18} /> : <Eye size={18} />}
                    </button>
                  </div>
                  {passwordForm.formState.errors.confirm_password && (
                    <span className="field__error">{passwordForm.formState.errors.confirm_password.message}</span>
                  )}
                </div>

                <button type="submit" className="auth-btn" disabled={passwordForm.formState.isSubmitting}>
                  {passwordForm.formState.isSubmitting ? (
                    <><Loader2 size={18} className="spin" /> جاري الحفظ...</>
                  ) : (
                    <><ShieldCheck size={18} /> حفظ كلمة المرور الجديدة</>
                  )}
                </button>
              </form>
            </motion.div>
          )}

          {/* ═══════ DONE ═══════ */}
          {step === 'done' && (
            <motion.div
              key="done"
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.4 }}
              className="forgot-success"
            >
              <motion.div
                className="forgot-success__icon"
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                transition={{ delay: 0.15, type: 'spring', stiffness: 300, damping: 20 }}
              >
                <CheckCircle2 size={48} strokeWidth={1.5} />
              </motion.div>

              <h1 className="auth-title">تم تغيير كلمة المرور!</h1>
              <p className="auth-subtitle">سيتم توجيهك لصفحة تسجيل الدخول خلال ثوانٍ...</p>
              <Link to="/auth/login" className="auth-btn" style={{ textDecoration: 'none', marginTop: '1.5rem', display: 'flex' }}>
                <LogIn size={18} />
                تسجيل الدخول الآن
              </Link>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </div>
  )
}
