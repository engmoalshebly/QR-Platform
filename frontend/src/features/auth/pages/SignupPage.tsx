import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { motion } from 'framer-motion'
import { Eye, EyeOff, UserPlus, Loader2, AlertCircle, CheckCircle2, Building2, Users, Clock, UploadCloud, FileCheck, X } from 'lucide-react'
import { authAPI } from '../api/authApi'
import { AuthShowcase } from './LoginPage'
import './auth.css'

type Mode = 'personal' | 'organizer'

/* ── Personal (instant) signup ── */
const personalSchema = z.object({
  full_name:         z.string().min(2, 'الاسم يجب أن يكون حرفين على الأقل'),
  organization_name: z.string().min(2, 'اسم المؤسسة يجب أن يكون حرفين على الأقل'),
  email:             z.string().email('بريد إلكتروني غير صالح'),
  password:          z.string()
    .min(12, 'كلمة المرور يجب أن تكون 12 حرفًا على الأقل')
    .regex(/[a-z]/, 'يجب أن تحتوي على حرف صغير')
    .regex(/[A-Z]/, 'يجب أن تحتوي على حرف كبير')
    .regex(/[0-9]/, 'يجب أن تحتوي على رقم'),
  confirm_password: z.string(),
}).refine(d => d.password === d.confirm_password, {
  message: 'كلمات المرور غير متطابقة',
  path: ['confirm_password'],
})
type PersonalForm = z.infer<typeof personalSchema>

/* ── Organizer-team request (awaits approval) ── */
const organizerSchema = z.object({
  full_name:   z.string().min(2, 'الاسم يجب أن يكون حرفين على الأقل'),
  email:       z.string().email('بريد إلكتروني غير صالح'),
  password:    z.string()
    .min(12, 'كلمة المرور يجب أن تكون 12 حرفًا على الأقل')
    .regex(/[a-z]/, 'يجب أن تحتوي على حرف صغير')
    .regex(/[A-Z]/, 'يجب أن تحتوي على حرف كبير')
    .regex(/[0-9]/, 'يجب أن تحتوي على رقم'),
  confirm_password: z.string(),
  phone:       z.string().trim().min(8, 'رقم الهاتف مطلوب ويجب أن يكون صحيحًا'),
  org_name:    z.string().min(2, 'اسم الفريق/المؤسسة مطلوب'),
  org_type:    z.string().optional(),
  description: z.string().optional(),
  city:        z.string().optional(),
  country:     z.string().optional(),
  website:     z.string().url('رابط غير صالح').optional().or(z.literal('')),
  contact_handle: z.string().optional(),
  expected_events_per_month: z.coerce.number().int().min(0).optional(),
  expected_attendees:        z.coerce.number().int().min(0).optional(),
  notes:       z.string().optional(),
}).refine(d => d.password === d.confirm_password, {
  message: 'كلمات المرور غير متطابقة',
  path: ['confirm_password'],
})
type OrganizerForm = z.infer<typeof organizerSchema>

const passwordRules = [
  { label: '12 حرفًا على الأقل', test: (p: string) => p.length >= 12 },
  { label: 'حرف صغير (a-z)',    test: (p: string) => /[a-z]/.test(p) },
  { label: 'حرف كبير (A-Z)',    test: (p: string) => /[A-Z]/.test(p) },
  { label: 'رقم (0-9)',         test: (p: string) => /[0-9]/.test(p) },
]

function apiErrorMessage(error: unknown, fallback: string): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const messages = detail
      .map(item => {
        if (typeof item === 'string') return item
        if (item && typeof item === 'object' && 'msg' in item) return String(item.msg)
        return ''
      })
      .filter(Boolean)
    if (messages.length) return messages.join('، ')
  }
  if (detail && typeof detail === 'object' && 'msg' in detail) return String(detail.msg)
  return fallback
}

export default function SignupPage() {
  const navigate = useNavigate()
  const [mode, setMode] = useState<Mode>('personal')

  return (
    <div className="auth-page">
      <div className="auth-orb auth-orb--1" />
      <div className="auth-orb auth-orb--2" />

      <main className="auth-layout auth-layout--signup">
        <AuthShowcase />
        <motion.div
          className="auth-card auth-card--wide"
          initial={{ opacity: 0, y: 24, scale: 0.97 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.5, ease: [0.34, 1.56, 0.64, 1] }}
        >
        <div className="auth-logo">
          <img src="/logo.png" alt="Qentry" className="auth-logo__img" />
        </div>

        <div className="auth-header">
          <h1 className="auth-title">إنشاء حساب جديد</h1>
          <p className="auth-subtitle">انضم إلى Qentry وابدأ رحلتك</p>
        </div>

        {/* Mode toggle */}
        <div className="auth-modes">
          <button
            type="button"
            className={`auth-mode ${mode === 'personal' ? 'auth-mode--active' : ''}`}
            onClick={() => setMode('personal')}
          >
            <UserPlus size={16} /> حساب عادي
          </button>
          <button
            type="button"
            className={`auth-mode ${mode === 'organizer' ? 'auth-mode--active' : ''}`}
            onClick={() => setMode('organizer')}
          >
            <Users size={16} /> فريق تنظيم
          </button>
        </div>

        {mode === 'personal'
          ? <PersonalSignup navigate={navigate} />
          : <OrganizerSignup />}

        <div className="auth-footer">
          <span>لديك حساب بالفعل؟</span>
          <Link to="/auth/login" className="auth-footer__link">تسجيل الدخول</Link>
        </div>
        </motion.div>
      </main>
    </div>
  )
}

/* ══════════════════════════════════════════════════
   PERSONAL (instant)
   ══════════════════════════════════════════════════ */
function PersonalSignup({ navigate }: { navigate: ReturnType<typeof useNavigate> }) {
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirm, setShowConfirm]   = useState(false)
  const [serverError, setServerError]   = useState('')

  const { register, handleSubmit, watch, formState: { errors, isSubmitting } } =
    useForm<PersonalForm>({ resolver: zodResolver(personalSchema) })
  const passwordValue = watch('password', '')

  const onSubmit = async (data: PersonalForm) => {
    setServerError('')
    try {
      await authAPI.signup({
        email: data.email, password: data.password,
        full_name: data.full_name, organization_name: data.organization_name,
      })
      navigate(`/auth/verify-signup?email=${encodeURIComponent(data.email)}`)
    } catch (err: unknown) {
      setServerError(apiErrorMessage(err, 'حدث خطأ، حاول مرة أخرى'))
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="auth-form" noValidate>
      {serverError && (
        <motion.div className="auth-error" initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }}>
          <AlertCircle size={16} /><span>{serverError}</span>
        </motion.div>
      )}
      <div className="auth-grid">
        <div className="field">
          <label className="field__label">الاسم الكامل</label>
          <input {...register('full_name')} type="text"
            className={`field__input ${errors.full_name ? 'field__input--error' : ''}`}
            placeholder="محمد العبدالله" />
          {errors.full_name && <span className="field__error">{errors.full_name.message}</span>}
        </div>
        <div className="field">
          <label className="field__label">اسم المؤسسة</label>
          <input {...register('organization_name')} type="text"
            className={`field__input ${errors.organization_name ? 'field__input--error' : ''}`}
            placeholder="شركة الأفق" />
          {errors.organization_name && <span className="field__error">{errors.organization_name.message}</span>}
        </div>
      </div>

      <div className="field">
        <label className="field__label">البريد الإلكتروني</label>
        <input {...register('email')} type="email"
          className={`field__input ${errors.email ? 'field__input--error' : ''}`}
          placeholder="you@company.com" dir="ltr" />
        {errors.email && <span className="field__error">{errors.email.message}</span>}
      </div>

      <div className="field">
        <label className="field__label">كلمة المرور</label>
        <div className="field__input-wrapper">
          <input {...register('password')} type={showPassword ? 'text' : 'password'}
            className={`field__input field__input--padded ${errors.password ? 'field__input--error' : ''}`}
            placeholder="••••••••" dir="ltr" />
          <button type="button" className="field__eye" onClick={() => setShowPassword(v => !v)} tabIndex={-1}>
            {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
          </button>
        </div>
        {passwordValue && (
          <div className="password-rules">
            {passwordRules.map(r => (
              <div key={r.label} className={`password-rule ${r.test(passwordValue) ? 'password-rule--ok' : ''}`}>
                <CheckCircle2 size={13} /><span>{r.label}</span>
              </div>
            ))}
          </div>
        )}
        {errors.password && <span className="field__error">{errors.password.message}</span>}
      </div>

      <div className="field">
        <label className="field__label">تأكيد كلمة المرور</label>
        <div className="field__input-wrapper">
          <input {...register('confirm_password')} type={showConfirm ? 'text' : 'password'}
            className={`field__input field__input--padded ${errors.confirm_password ? 'field__input--error' : ''}`}
            placeholder="••••••••" dir="ltr" />
          <button type="button" className="field__eye" onClick={() => setShowConfirm(v => !v)} tabIndex={-1}>
            {showConfirm ? <EyeOff size={18} /> : <Eye size={18} />}
          </button>
        </div>
        {errors.confirm_password && <span className="field__error">{errors.confirm_password.message}</span>}
      </div>

      <button type="submit" className="auth-btn" disabled={isSubmitting}>
        {isSubmitting
          ? <><Loader2 size={18} className="spin" /> جاري إنشاء الحساب...</>
          : <><UserPlus size={18} /> إنشاء الحساب</>}
      </button>
    </form>
  )
}

/* ══════════════════════════════════════════════════
   ORGANIZER TEAM (request → platform approval)
   ══════════════════════════════════════════════════ */
function OrganizerSignup() {
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirm, setShowConfirm]   = useState(false)
  const [serverError, setServerError]   = useState('')
  const [submitted, setSubmitted]        = useState(false)
  const [step, setStep]                  = useState(1)
  const [proofFile, setProofFile]         = useState<File | null>(null)
  const [documentsFile, setDocumentsFile] = useState<File | null>(null)

  const { register, handleSubmit, watch, trigger, formState: { errors, isSubmitting } } =
    useForm<OrganizerForm>({ resolver: zodResolver(organizerSchema) })
  const passwordValue = watch('password', '')

  const onSubmit = async (data: OrganizerForm) => {
    setServerError('')
    try {
      if (!proofFile) {
        setServerError('يرجى رفع مستند إثبات واحد على الأقل')
        setStep(3)
        return
      }
      const proof = await authAPI.uploadOrgDocument(proofFile)
      const documents = documentsFile ? await authAPI.uploadOrgDocument(documentsFile) : null
      await authAPI.orgRequest({
        full_name: data.full_name, email: data.email, password: data.password,
        phone: data.phone || undefined,
        org_name: data.org_name, org_type: data.org_type || undefined,
        description: data.description || undefined,
        city: data.city || undefined, country: data.country || undefined,
        website: data.website || undefined, contact_handle: data.contact_handle || undefined,
        expected_events_per_month: data.expected_events_per_month,
        expected_attendees: data.expected_attendees,
        proof_url: proof.file_key, documents_url: documents?.file_key,
        notes: data.notes || undefined,
      })
      setSubmitted(true)
    } catch (err: unknown) {
      setServerError(apiErrorMessage(err, 'حدث خطأ، حاول مرة أخرى'))
    }
  }

  if (submitted) {
    return (
      <motion.div className="auth-pending" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
        <div className="auth-pending__icon"><Clock size={40} /></div>
        <h2 className="auth-pending__title">طلبك قيد المراجعة</h2>
        <p className="auth-pending__text">
          استلمنا طلب تسجيل فريق التنظيم الخاص بك. سيقوم فريق المنصة بمراجعته،
          وستصلك رسالة على بريدك الإلكتروني فور الموافقة لتتمكن من تسجيل الدخول.
        </p>
        <div className="organizer-request-confirmation">
          <strong>تم استلام طلبك بنجاح</strong>
          <span>سيتم التواصل معك عبر البريد الإلكتروني: <b dir="ltr">{watch('email')}</b></span>
          <small>ستصلك نتيجة المراجعة عبر البريد الإلكتروني.</small>
        </div>
        <Link to="/auth/login" className="auth-btn auth-btn--inline">العودة لتسجيل الدخول</Link>
      </motion.div>
    )
  }

  const nextStep = async () => {
    if (step === 3) {
      if (!proofFile) setServerError('يرجى رفع مستند إثبات واحد على الأقل')
      return
    }
    const fields = step === 1
      ? ['full_name', 'email', 'password', 'confirm_password'] as const
      : ['org_name'] as const
    if (await trigger(fields)) setStep(value => Math.min(3, value + 1))
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="auth-form organizer-wizard" noValidate>
      <div className="auth-note">
        <Building2 size={16} />
        <span>تسجيل فريق التنظيم يتطلب موافقة إدارة المنصة. لن يتم إنشاء الحساب إلا بعد الموافقة.</span>
      </div>

      {serverError && (
        <motion.div className="auth-error" initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }}>
          <AlertCircle size={16} /><span>{serverError}</span>
        </motion.div>
      )}

      <div className="organizer-progress" aria-label="مراحل الطلب">
        {[['1', 'بياناتك'], ['2', 'الفريق'], ['3', 'التفاصيل']].map(([number, label]) => (
          <div key={number} className={`organizer-progress__item ${Number(number) <= step ? 'is-active' : ''}`}>
            <span>{number}</span><small>{label}</small>
          </div>
        ))}
      </div>

      {step === 1 && <div className="organizer-wizard__step">
      <div className="auth-section-label">بيانات مقدم الطلب</div>
      <div className="auth-grid">
        <div className="field">
          <label className="field__label">الاسم الكامل</label>
          <input {...register('full_name')} type="text"
            className={`field__input ${errors.full_name ? 'field__input--error' : ''}`}
            placeholder="محمد العبدالله" />
          {errors.full_name && <span className="field__error">{errors.full_name.message}</span>}
        </div>
        <div className="field">
          <label className="field__label">رقم الجوال *</label>
          <input {...register('phone')} type="tel"
            className={`field__input ${errors.phone ? 'field__input--error' : ''}`} placeholder="05xxxxxxxx" dir="ltr" />
          {errors.phone && <span className="field__error">{errors.phone.message}</span>}
        </div>
      </div>

      <div className="field">
        <label className="field__label">البريد الإلكتروني</label>
        <input {...register('email')} type="email"
          className={`field__input ${errors.email ? 'field__input--error' : ''}`}
          placeholder="you@company.com" dir="ltr" />
        {errors.email && <span className="field__error">{errors.email.message}</span>}
      </div>

      <div className="auth-grid">
        <div className="field">
          <label className="field__label">كلمة المرور</label>
          <div className="field__input-wrapper">
            <input {...register('password')} type={showPassword ? 'text' : 'password'}
              className={`field__input field__input--padded ${errors.password ? 'field__input--error' : ''}`}
              placeholder="••••••••" dir="ltr" />
            <button type="button" className="field__eye" onClick={() => setShowPassword(v => !v)} tabIndex={-1}>
              {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
            </button>
          </div>
          {errors.password && <span className="field__error">{errors.password.message}</span>}
        </div>
        <div className="field">
          <label className="field__label">تأكيد كلمة المرور</label>
          <div className="field__input-wrapper">
            <input {...register('confirm_password')} type={showConfirm ? 'text' : 'password'}
              className={`field__input field__input--padded ${errors.confirm_password ? 'field__input--error' : ''}`}
              placeholder="••••••••" dir="ltr" />
            <button type="button" className="field__eye" onClick={() => setShowConfirm(v => !v)} tabIndex={-1}>
              {showConfirm ? <EyeOff size={18} /> : <Eye size={18} />}
            </button>
          </div>
          {errors.confirm_password && <span className="field__error">{errors.confirm_password.message}</span>}
        </div>
      </div>
      {passwordValue && (
        <div className="password-rules">
          {passwordRules.map(r => (
            <div key={r.label} className={`password-rule ${r.test(passwordValue) ? 'password-rule--ok' : ''}`}>
              <CheckCircle2 size={13} /><span>{r.label}</span>
            </div>
          ))}
        </div>
      )}
      </div>}

      {step === 2 && <div className="organizer-wizard__step">
      <div className="auth-section-label">بيانات المؤسسة / الفريق</div>
      <div className="auth-grid">
        <div className="field">
          <label className="field__label">اسم الفريق / المؤسسة</label>
          <input {...register('org_name')} type="text"
            className={`field__input ${errors.org_name ? 'field__input--error' : ''}`}
            placeholder="فريق أفق للتنظيم" />
          {errors.org_name && <span className="field__error">{errors.org_name.message}</span>}
        </div>
        <div className="field">
          <label className="field__label">نوع النشاط</label>
          <input {...register('org_type')} type="text"
            className="field__input" placeholder="تنظيم فعاليات، مؤتمرات..." />
        </div>
      </div>

      <div className="field">
        <label className="field__label">وصف مختصر</label>
        <textarea {...register('description')} rows={2}
          className="field__input" placeholder="نبذة عن نشاط الفريق وخبراته" />
      </div>

      <div className="auth-grid">
        <div className="field">
          <label className="field__label">المدينة</label>
          <input {...register('city')} type="text" className="field__input" placeholder="الرياض" />
        </div>
        <div className="field">
          <label className="field__label">الدولة</label>
          <input {...register('country')} type="text" className="field__input" placeholder="السعودية" />
        </div>
      </div>

      <div className="auth-grid">
        <div className="field">
          <label className="field__label">الموقع الإلكتروني (اختياري)</label>
          <input {...register('website')} type="url"
            className={`field__input ${errors.website ? 'field__input--error' : ''}`}
            placeholder="https://..." dir="ltr" />
          {errors.website && <span className="field__error">{errors.website.message}</span>}
        </div>
        <div className="field">
          <label className="field__label">حساب التواصل (اختياري)</label>
          <input {...register('contact_handle')} type="text"
            className="field__input" placeholder="@account" dir="ltr" />
        </div>
      </div>
      </div>}

      {step === 3 && <div className="organizer-wizard__step">
      <div className="auth-section-label">حجم النشاط المتوقع</div>
      <div className="auth-grid">
        <div className="field">
          <label className="field__label">عدد الفعاليات شهرياً</label>
          <input {...register('expected_events_per_month')} type="number" min={0}
            className="field__input" placeholder="5" dir="ltr" />
        </div>
        <div className="field">
          <label className="field__label">الحضور المتوقع للفعالية</label>
          <input {...register('expected_attendees')} type="number" min={0}
            className="field__input" placeholder="2000" dir="ltr" />
        </div>
      </div>

      <div className="auth-section-label">الإثبات والمستندات</div>
      <div className="field">
        <label className="field__label">مستند إثبات الفريق *</label>
        <label className="organizer-file-input">
          <UploadCloud size={19} />
          <span>{proofFile ? proofFile.name : 'اختر PDF أو صورة لإثبات نشاط الفريق'}</span>
          <input type="file" accept="application/pdf,image/jpeg,image/png,image/webp" onChange={e => setProofFile(e.target.files?.[0] || null)} />
        </label>
        {proofFile && <div className="organizer-file-selected"><FileCheck size={14} /> تم اختيار الملف <button type="button" onClick={() => setProofFile(null)}><X size={14} /></button></div>}
      </div>
      <div className="field">
        <label className="field__label">مستند إضافي (اختياري)</label>
        <label className="organizer-file-input">
          <UploadCloud size={19} />
          <span>{documentsFile ? documentsFile.name : 'أرفق ترخيصًا أو ملفًا إضافيًا'}</span>
          <input type="file" accept="application/pdf,image/jpeg,image/png,image/webp" onChange={e => setDocumentsFile(e.target.files?.[0] || null)} />
        </label>
        {documentsFile && <div className="organizer-file-selected"><FileCheck size={14} /> تم اختيار الملف <button type="button" onClick={() => setDocumentsFile(null)}><X size={14} /></button></div>}
      </div>
      <div className="field">
        <label className="field__label">ملاحظات للإدارة (اختياري)</label>
        <textarea {...register('notes')} rows={2}
          className="field__input" placeholder="أي معلومات إضافية تساعد في مراجعة طلبك" />
      </div>
      </div>}

      <div className="organizer-wizard__actions">
        {step > 1 && <button type="button" className="auth-btn auth-btn--secondary" onClick={() => setStep(value => value - 1)} disabled={isSubmitting}>السابق</button>}
        {step < 3
          ? <button type="button" className="auth-btn" onClick={nextStep}>التالي</button>
          : <button type="submit" className="auth-btn" disabled={isSubmitting}>
        {isSubmitting
          ? <><Loader2 size={18} className="spin" /> جاري إرسال الطلب...</>
          : <><Users size={18} /> إرسال طلب التسجيل</>}
          </button>}
      </div>
    </form>
  )
}
