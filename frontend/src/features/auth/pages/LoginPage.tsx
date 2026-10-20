import { AuthShowcase } from '../components/AuthShowcase'
import { BrandLogo } from '@components/BrandLogo'
import { getApiErrorMessage } from '@services/http/client'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useSearchParams } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { motion } from 'framer-motion'
import { useQueryClient } from '@tanstack/react-query'
import { Building2, BriefcaseBusiness, Eye, EyeOff, LogIn, Loader2, AlertCircle } from 'lucide-react'
import { authAPI, tokenAal } from '../api/authApi'
import { useAuthStore } from '../store/authStore'
import type { AuthUser, TenantInfo } from '../types'
import './auth.css'

const schema = z.object({
  email:    z.string().email('بريد إلكتروني غير صالح'),
  password: z.string().min(6, 'كلمة المرور يجب أن تكون 6 أحرف على الأقل'),
})
type FormData = z.infer<typeof schema>

export default function LoginPage() {
  const navigate  = useNavigate()
  const queryClient = useQueryClient()
  const [searchParams] = useSearchParams()
  const setAuth   = useAuthStore(s => s.setAuth)
  const setPermissions = useAuthStore(s => s.setPermissions)
  const [showPassword, setShowPassword] = useState(false)
  const [serverError, setServerError]   = useState('')
  const [workspaceChoices, setWorkspaceChoices] = useState<{ user: AuthUser; tenants: TenantInfo[] } | null>(null)
  const [selectingWorkspace, setSelectingWorkspace] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormData>({ resolver: zodResolver(schema), defaultValues: { email: searchParams.get('email') || '' } })

  const enterWorkspace = async (user: AuthUser, tenants: TenantInfo[], tenant: TenantInfo) => {
    setSelectingWorkspace(tenant.tenant_id)
    setServerError('')
    try {
      setAuth(user, tenants, tenant.tenant_id, [])
      const scopedProfile = await authAPI.me()
      setPermissions(scopedProfile.permissions || [])
      navigate(tenant.workspace_type === 'organizer' ? '/teams' : '/dashboard', { replace: true })
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } }
      setServerError(getApiErrorMessage(e, 'تعذر فتح مساحة العمل، حاول مرة أخرى'))
      setSelectingWorkspace(null)
    }
  }

  const onSubmit = async (data: FormData) => {
    setServerError('')
    try {
      // Do not let responses cached for the previous account determine this
      // account's permissions, workspace type, or navigation.
      queryClient.clear()
      const res = await authAPI.login(data)

      // Fetch actual profile from /auth/me to get real name, is_staff status, etc.
      let profile;
      try {
        profile = await authAPI.me()
      } catch (err) {
        console.error('Failed to fetch user profile', err)
      }

      const user: AuthUser = {
        id:         profile?.user_id || res.user_id!,
        email:      profile?.email || data.email,
        full_name:  profile?.full_name || null,
        avatar_url: profile?.avatar_url || null,
        is_staff:   profile?.is_staff || false,
      }

      const tenants = res.tenants || profile?.tenants || []
      const invite = searchParams.get('invite')
      if (invite) {
        setAuth(user, tenants, undefined, profile?.permissions || [])
        navigate(`/invites/accept/${encodeURIComponent(invite)}`, { replace: true })
      } else if (user.is_staff) {
        // Platform administrators are deliberately not members of a tenant.
        // Do not request tenant-scoped booking context for this account.
        setAuth(user, tenants, undefined, profile?.permissions || [])
        // Production requires an AAL2 (TOTP-verified) session for staff.
        const needsMfa = !['aal2', 'aal3'].includes(tokenAal(res.access_token) || '')
        navigate(needsMfa ? '/auth/mfa' : '/platform', { replace: true })
      } else if (res.requires_tenant_selection && tenants.length > 1) {
        setWorkspaceChoices({ user, tenants })
      } else {
        const tenant = tenants[0]
        if (!tenant) throw new Error('لا توجد مساحة عمل نشطة لهذا الحساب')
        await enterWorkspace(user, tenants, tenant)
      }
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } }
      setServerError(getApiErrorMessage(e, 'حدث خطأ، حاول مرة أخرى'))
    }
  }

  if (workspaceChoices) {
    return (
      <div className="auth-page">
        <div className="auth-orb auth-orb--1" />
        <div className="auth-orb auth-orb--2" />
        <main className="auth-layout">
        <AuthShowcase />
        <motion.div className="auth-card workspace-choice" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}>
          <div className="auth-logo"><BrandLogo /></div>
          <div className="auth-header">
            <h1 className="auth-title">اختر مساحة العمل</h1>
            <p className="auth-subtitle">يمكنك التبديل بين المساحات لاحقاً من القائمة العلوية.</p>
          </div>
          <div className="workspace-choice__list">
            {workspaceChoices.tenants.map((tenant) => {
              const isOrganizer = tenant.workspace_type === 'organizer'
              const Icon = isOrganizer ? BriefcaseBusiness : Building2
              return (
                <button
                  type="button"
                  className={`workspace-choice__item workspace-choice__item--${tenant.workspace_type}`}
                  key={tenant.tenant_id}
                  onClick={() => enterWorkspace(workspaceChoices.user, workspaceChoices.tenants, tenant)}
                  disabled={Boolean(selectingWorkspace)}
                >
                  <span className="workspace-choice__icon"><Icon /></span>
                  <span className="workspace-choice__copy">
                    <strong>{isOrganizer ? 'إدارة فريق التنظيم' : 'دخول المؤسسة'}</strong>
                    <small>{tenant.name}</small>
                    <em>{isOrganizer ? 'الطلبات والعمليات وفريق التنفيذ' : 'الحفلات والدعوات وإدارة المؤسسة'}</em>
                  </span>
                  {selectingWorkspace === tenant.tenant_id ? <Loader2 className="spin" /> : <span className="workspace-choice__arrow">←</span>}
                </button>
              )
            })}
          </div>
          {serverError && <div className="auth-error"><AlertCircle size={16} />{serverError}</div>}
        </motion.div>
        </main>
      </div>
    )
  }

  return (
    <div className="auth-page">
      {/* Background Orbs */}
      <div className="auth-orb auth-orb--1" />
      <div className="auth-orb auth-orb--2" />

      <main className="auth-layout">
      <AuthShowcase />
      <motion.div
        className="auth-card"
        initial={{ opacity: 0, y: 24, scale: 0.97 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.5, ease: [0.34, 1.56, 0.64, 1] }}
      >
        {/* Logo */}
        <div className="auth-logo">
          <BrandLogo />
        </div>

        <div className="auth-header">
          <h1 className="auth-title">مرحباً بعودتك</h1>
          <p className="auth-subtitle">سجّل دخولك للمتابعة</p>
        </div>

        <form onSubmit={handleSubmit(onSubmit)} className="auth-form" noValidate>

          {/* Server Error */}
          {serverError && (
            <motion.div
              className="auth-error"
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
            >
              <AlertCircle size={16} />
              <span>{serverError}</span>
            </motion.div>
          )}

          {/* Email */}
          <div className="field">
            <label className="field__label">البريد الإلكتروني</label>
            <input
              {...register('email')}
              type="email"
              className={`field__input ${errors.email ? 'field__input--error' : ''}`}
              placeholder="you@example.com"
              autoComplete="email"
              dir="ltr"
            />
            {errors.email && (
              <span className="field__error">{errors.email.message}</span>
            )}
          </div>

          {/* Password */}
          <div className="field">
            <div className="field__label-row">
              <label className="field__label">كلمة المرور</label>
              <Link to="/auth/forgot-password" className="field__link">
                نسيت كلمة المرور؟
              </Link>
            </div>
            <div className="field__input-wrapper">
              <input
                {...register('password')}
                type={showPassword ? 'text' : 'password'}
                className={`field__input field__input--padded ${errors.password ? 'field__input--error' : ''}`}
                placeholder="••••••••"
                autoComplete="current-password"
                dir="ltr"
              />
              <button
                type="button"
                className="field__eye"
                onClick={() => setShowPassword(v => !v)}
                tabIndex={-1}
              >
                {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
            {errors.password && (
              <span className="field__error">{errors.password.message}</span>
            )}
          </div>

          {/* Submit */}
          <button type="submit" className="auth-btn" disabled={isSubmitting}>
            {isSubmitting ? (
              <><Loader2 size={18} className="spin" /> جاري تسجيل الدخول...</>
            ) : (
              <><LogIn size={18} /> تسجيل الدخول</>
            )}
          </button>

        </form>

        <div className="auth-footer">
          <span>ليس لديك حساب؟</span>
          <Link to="/auth/signup" className="auth-footer__link">إنشاء حساب جديد</Link>
        </div>
      </motion.div>
      </main>
    </div>
  )
}
