import { LimitErrorNotice } from '@components/LimitErrorNotice'
/**
 * CreateEventDialog.tsx
 * Modal dialog for creating a new event.
 * Mutation is delegated to useEventCreate hook for consistent cache invalidation.
 */
import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, Loader2 } from 'lucide-react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useAuthStore } from '@features/auth/store/authStore'
import { useEventCreate } from '../hooks/useEvents'
import type { EventCreateRequest } from '../types'

// ── Validation ───────────────────────────────────────────────────
const schema = z.object({
  title: z.string().min(3, 'العنوان يجب أن يكون 3 أحرف على الأقل'),
  start_date: z.string().min(1, 'تاريخ البداية مطلوب'),
  vip_quota: z.number({ invalid_type_error: 'يجب أن يكون رقماً' }).min(0),
  normal_quota: z.number({ invalid_type_error: 'يجب أن يكون رقماً' }).min(0),
})

type FormData = z.infer<typeof schema>

interface Props {
  isOpen: boolean
  onClose: () => void
}

export function CreateEventDialog({ isOpen, onClose }: Props) {
  const currentTenantId = useAuthStore((s) => s.currentTenantId)
  const [serverError, setServerError] = useState<unknown>(null)

  const createMutation = useEventCreate(currentTenantId)

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: { vip_quota: 0, normal_quota: 100 },
  })

  const onSubmit = (data: FormData) => {
    setServerError('')
    const payload: EventCreateRequest = {
      title: data.title,
      start_date: new Date(data.start_date).toISOString(),
      vip_quota: data.vip_quota,
      normal_quota: data.normal_quota,
      timezone: 'Asia/Riyadh',
      venue_country: 'SA',
    }
    createMutation.mutate(payload, {
      onSuccess: () => {
        reset()
        onClose()
        // Navigation handled inside useEventCreate hook
      },
      onError: (err: any) => {
        setServerError(err)
      },
    })
  }

  if (!isOpen) return null

  const pending = isSubmitting || createMutation.isPending

  return (
    <AnimatePresence>
      <div className="dialog-overlay">
        <motion.div
          className="dialog-content"
          initial={{ opacity: 0, scale: 0.94, y: 14 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.94, y: 14 }}
          transition={{ type: 'spring', stiffness: 380, damping: 28 }}
        >
          {/* Header */}
          <div className="dialog-header">
            <h3>إنشاء مناسبة جديدة</h3>
            <button className="dialog-close" onClick={onClose} aria-label="إغلاق">
              <X size={20} />
            </button>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit(onSubmit)} className="dialog-form" noValidate>
            {/* Server error */}
            <LimitErrorNotice error={serverError} onRetry={handleSubmit(onSubmit)} busy={pending} />

            {/* Title */}
            <div className="form-field">
              <label htmlFor="ev-title">عنوان المناسبة</label>
              <input
                id="ev-title"
                {...register('title')}
                type="text"
                placeholder="مثال: مؤتمر التقنية السنوي"
                className={errors.title ? 'error' : ''}
                autoFocus
              />
              {errors.title && <span className="form-error">{errors.title.message}</span>}
            </div>

            {/* Date */}
            <div className="form-field">
              <label htmlFor="ev-date">تاريخ ووقت البداية</label>
              <input
                id="ev-date"
                {...register('start_date')}
                type="datetime-local"
                className={errors.start_date ? 'error' : ''}
              />
              {errors.start_date && (
                <span className="form-error">{errors.start_date.message}</span>
              )}
            </div>

            {/* Quotas */}
            <div className="event-form-grid" style={{ gridTemplateColumns: '1fr 1fr', gap: 16 }}>
              <div className="form-field">
                <label htmlFor="ev-vip">تذاكر VIP</label>
                <input
                  id="ev-vip"
                  {...register('vip_quota', { valueAsNumber: true })}
                  type="number"
                  min="0"
                  className={errors.vip_quota ? 'error' : ''}
                />
                {errors.vip_quota && (
                  <span className="form-error">{errors.vip_quota.message}</span>
                )}
              </div>
              <div className="form-field">
                <label htmlFor="ev-normal">التذاكر العادية</label>
                <input
                  id="ev-normal"
                  {...register('normal_quota', { valueAsNumber: true })}
                  type="number"
                  min="0"
                  className={errors.normal_quota ? 'error' : ''}
                />
                {errors.normal_quota && (
                  <span className="form-error">{errors.normal_quota.message}</span>
                )}
              </div>
            </div>

            <p className="form-hint">
              يمكنك إضافة المزيد من التفاصيل (الموقع، الإعدادات المتقدمة…) بعد الإنشاء.
            </p>

            {/* Actions */}
            <div className="dialog-actions">
              <button type="button" className="btn btn-ghost" onClick={onClose} disabled={pending}>
                إلغاء
              </button>
              <button type="submit" className="btn btn-primary" disabled={pending}>
                {pending ? (
                  <>
                    <Loader2 size={16} className="spin" />
                    جاري الإنشاء…
                  </>
                ) : (
                  'إنشاء المناسبة'
                )}
              </button>
            </div>
          </form>
        </motion.div>
      </div>
    </AnimatePresence>
  )
}
