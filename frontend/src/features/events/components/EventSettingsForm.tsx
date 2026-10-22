import { LimitErrorNotice } from '@components/LimitErrorNotice'
import { getApiErrorMessage } from '@services/http/client'
/**
 * EventSettingsForm.tsx
 * Edit form for event settings — extracted from EventDetailsPage.
 * Has Zod validation, error handling, and success toast feedback.
 */
import { useState, useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Loader2, CheckCircle2, AlertCircle, UploadCloud, Camera } from 'lucide-react'
import type { EventModel, EventUpdateRequest } from '../types'
import { useEventUpdate, useEventCoverUpload } from '../hooks/useEventDetails'
import { usePermission } from '@shared/permissions'

// ── Validation Schema ────────────────────────────────────────────
const schema = z.object({
  title: z.string().min(3, 'العنوان يجب أن يكون 3 أحرف على الأقل'),
  start_date: z.string().min(1, 'التاريخ مطلوب'),
  venue_name: z.string().optional(),
  venue_address: z.string().optional(),
  venue_city: z.string().optional(),
  vip_quota: z.number({ invalid_type_error: 'يجب أن يكون رقماً' }).min(0),
  normal_quota: z.number({ invalid_type_error: 'يجب أن يكون رقماً' }).min(0),
  allow_rsvp: z.boolean(),
  allow_plus_one: z.boolean(),
  allow_reentry: z.boolean(),
})

type FormData = z.infer<typeof schema>

interface Props {
  event: EventModel
  tenantId: string | null
}

export function EventSettingsForm({ event, tenantId }: Props) {
  const canEdit = usePermission('events.edit')
  const [toast, setToast] = useState<'success' | 'error' | null>(null)
  const [serverError, setServerError] = useState<unknown>(null)
  const [uploadError, setUploadError] = useState('')

  const updateMutation = useEventUpdate(tenantId, event.id)
  const coverUploadMutation = useEventCoverUpload(tenantId, event.id)

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    await uploadFile(file)
  }

  const uploadFile = async (file: File) => {
    setUploadError('')
    const validTypes = ['image/png', 'image/jpeg', 'image/jpg', 'image/webp']
    if (!validTypes.includes(file.type)) {
      setUploadError('الامتداد غير مدعوم. يرجى رفع صورة PNG, JPG أو WEBP')
      return
    }
    if (file.size > 10 * 1024 * 1024) {
      setUploadError('حجم الصورة كبير جداً. الحد الأقصى المسموح به هو 10 ميجابايت')
      return
    }

    try {
      await coverUploadMutation.mutateAsync(file)
    } catch (err: any) {
      setUploadError(getApiErrorMessage(err, 'فشل رفع الصورة، يرجى المحاولة لاحقاً'))
    }
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
  }

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault()
    const file = e.dataTransfer.files?.[0]
    if (file) {
      await uploadFile(file)
    }
  }

  const {
    register,
    handleSubmit,
    watch,
    setValue,
    formState: { errors, isDirty, isSubmitting },
    reset,
  } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: {
      title: event.title,
      start_date: new Date(event.start_date).toISOString().slice(0, 16),
      venue_name: event.venue_name ?? '',
      venue_address: event.venue_address ?? '',
      venue_city: event.venue_city ?? '',
      vip_quota: event.vip_quota,
      normal_quota: event.normal_quota,
      allow_rsvp: event.allow_rsvp,
      allow_plus_one: event.allow_plus_one,
      allow_reentry: event.allow_reentry,
    },
  })

  // Reset form when event prop changes (e.g., after publish)
  useEffect(() => {
    reset({
      title: event.title,
      start_date: new Date(event.start_date).toISOString().slice(0, 16),
      venue_name: event.venue_name ?? '',
      venue_address: event.venue_address ?? '',
      venue_city: event.venue_city ?? '',
      vip_quota: event.vip_quota,
      normal_quota: event.normal_quota,
      allow_rsvp: event.allow_rsvp,
      allow_plus_one: event.allow_plus_one,
      allow_reentry: event.allow_reentry,
    })
  }, [
    event.allow_plus_one,
    event.allow_reentry,
    event.allow_rsvp,
    event.normal_quota,
    event.start_date,
    event.title,
    event.venue_address,
    event.venue_city,
    event.venue_name,
    event.vip_quota,
    reset,
  ])

  const onSubmit = async (data: FormData) => {
    setServerError('')
    setToast(null)
    try {
      const payload: EventUpdateRequest = {
        ...data,
        start_date: new Date(data.start_date).toISOString(),
      }
      await updateMutation.mutateAsync(payload)
      reset(data) // mark form as clean
      setToast('success')
      setTimeout(() => setToast(null), 3000)
    } catch (err: any) {
      setServerError(err)
      setToast('error')
    }
  }

  // Watched booleans for custom toggle display
  const allowRsvp = watch('allow_rsvp')
  const allowPlusOne = watch('allow_plus_one')
  const allowReentry = watch('allow_reentry')

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="event-form-section" noValidate>
      {/* ── Success / Error Toast ── */}
      {toast === 'success' && (
        <div className="form-toast form-toast--success">
          <CheckCircle2 size={16} />
          <span>تم حفظ التعديلات بنجاح</span>
        </div>
      )}
      <LimitErrorNotice error={serverError || (toast === 'error' ? 'فشل الحفظ، يُرجى المحاولة مجدداً' : null)} />

      {/* ── Section: Event Cover Image ── */}
      <h3 className="section-title">غلاف المناسبة</h3>
      <div className="event-cover-upload-container">
        {event.cover_image_url ? (
          <div 
            className="event-cover-preview"
            style={{ backgroundImage: `url(${event.cover_image_url})` }}
          >
            <div className="event-cover-preview-overlay">
              <label className="btn btn-secondary btn-sm cover-upload-btn">
                {coverUploadMutation.isPending ? (
                  <Loader2 size={14} className="spin" />
                ) : (
                  <Camera size={14} />
                )}
                <span>{coverUploadMutation.isPending ? 'جاري الرفع...' : 'تغيير الغلاف'}</span>
                <input 
                  type="file" 
                  accept="image/*" 
                  onChange={handleFileChange} 
                  style={{ display: 'none' }} 
                  disabled={coverUploadMutation.isPending}
                />
              </label>
            </div>
          </div>
        ) : (
          <div 
            className="event-cover-dropzone"
            onDragOver={handleDragOver}
            onDrop={handleDrop}
          >
            <input 
              type="file" 
              id="event-cover-input"
              accept="image/*" 
              onChange={handleFileChange} 
              style={{ display: 'none' }}
              disabled={coverUploadMutation.isPending}
            />
            <label htmlFor="event-cover-input" className="event-cover-dropzone-label">
              {coverUploadMutation.isPending ? (
                <Loader2 size={32} className="spin gold-text" />
              ) : (
                <UploadCloud size={32} className="gold-text" />
              )}
              <div className="event-cover-dropzone-text">
                <strong>اسحب صورة الغلاف هنا أو انقر لتصفح الملفات</strong>
                <span>الصيغ المدعومة: PNG, JPG, WEBP (الحد الأقصى 10MB)</span>
              </div>
            </label>
          </div>
        )}
        
        {uploadError && (
          <div className="cover-upload-error">
            <AlertCircle size={14} />
            <span>{uploadError}</span>
          </div>
        )}
      </div>

      {/* ── Section: Basic Info ── */}
      <h3 className="section-title">البيانات الأساسية</h3>
      <div className="event-form-grid">
        <div className="form-field">
          <label>عنوان المناسبة</label>
          <input {...register('title')} type="text" className={errors.title ? 'error' : ''} />
          {errors.title && <span className="form-error">{errors.title.message}</span>}
        </div>
        <div className="form-field">
          <label>تاريخ ووقت المناسبة</label>
          <input
            {...register('start_date')}
            type="datetime-local"
            className={errors.start_date ? 'error' : ''}
          />
          {errors.start_date && <span className="form-error">{errors.start_date.message}</span>}
        </div>
      </div>

      {/* ── Section: Venue & Capacity ── */}
      <h3 className="section-title" style={{ marginTop: 28 }}>المكان والسعة</h3>
      <div className="event-form-grid">
        <div className="form-field">
          <label>اسم القاعة / المكان</label>
          <input
            {...register('venue_name')}
            type="text"
            placeholder="مثال: قاعة الملك فيصل للمؤتمرات"
          />
        </div>
        <div className="form-field">
          <label>المدينة</label>
          <input {...register('venue_city')} type="text" placeholder="مثال: الرياض" />
        </div>
        <div className="form-field" style={{ gridColumn: '1 / -1' }}>
          <label>عنوان مكان المناسبة</label>
          <input
            {...register('venue_address')}
            type="text"
            placeholder="مثال: طريق الملك فهد، حي العليا، الرياض"
          />
        </div>
        <div className="form-field">
          <label>حصة تذاكر VIP</label>
          <input
            {...register('vip_quota', { valueAsNumber: true })}
            type="number"
            min={0}
            className={errors.vip_quota ? 'error' : ''}
          />
          {errors.vip_quota && <span className="form-error">{errors.vip_quota.message}</span>}
        </div>
        <div className="form-field">
          <label>الحصة العادية</label>
          <input
            {...register('normal_quota', { valueAsNumber: true })}
            type="number"
            min={0}
            className={errors.normal_quota ? 'error' : ''}
          />
          {errors.normal_quota && <span className="form-error">{errors.normal_quota.message}</span>}
        </div>
      </div>

      {/* ── Section: Rules ── */}
      <h3 className="section-title" style={{ marginTop: 28 }}>قواعد الدعوات والدخول</h3>
      <div className="event-toggles-grid">
        <ToggleRow
          label="السماح بتأكيد الحضور"
          description="يسمح للضيوف بتسجيل الحضور أو الاعتذار. لا يجعل التأكيد شرطاً للدخول وحده؛ حدد اشتراط التأكيد أثناء إنشاء الدعوات."
          value={allowRsvp}
          onChange={(v) => setValue('allow_rsvp', v, { shouldDirty: true })}
        />
        <ToggleRow
          label="مرافق (Plus One)"
          description="السماح للضيف بدعوة شخص إضافي ليتواجد معه"
          value={allowPlusOne}
          onChange={(v) => setValue('allow_plus_one', v, { shouldDirty: true })}
        />
        <ToggleRow
          label="إعادة الدخول"
          description="السماح للضيف بالدخول والخروج أكثر من مرة"
          value={allowReentry}
          onChange={(v) => setValue('allow_reentry', v, { shouldDirty: true })}
        />
      </div>

      {/* ── Submit ── */}
      {canEdit && (
        <div className="form-actions">
          <button
            type="submit"
            className="btn btn-primary"
            disabled={!isDirty || isSubmitting || updateMutation.isPending}
          >
            {isSubmitting || updateMutation.isPending ? (
              <>
                <Loader2 size={16} className="spin" />
                جاري الحفظ…
              </>
            ) : (
              'حفظ التعديلات'
            )}
          </button>
        </div>
      )}
    </form>
  )
}

// ── Toggle Row ───────────────────────────────────────────────────
function ToggleRow({
  label,
  description,
  value,
  onChange,
}: {
  label: string
  description: string
  value: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <button
      type="button"
      className={`toggle-row ${value ? 'toggle-row--on' : ''}`}
      onClick={() => onChange(!value)}
      role="switch"
      aria-checked={value}
    >
      <div className="toggle-row-info">
        <h4>{label}</h4>
        <p>{description}</p>
      </div>
      <div className={`toggle-switch ${value ? 'toggle-switch--on' : ''}`}>
        <div className="toggle-switch__thumb" />
      </div>
    </button>
  )
}
