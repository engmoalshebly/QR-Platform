/**
 * EventRegistrationTab.tsx
 * Overhauled Premium Admin UI for configuring event self-registration forms, dynamic fields,
 * public registration link delivery, and ticket generation behavior.
 */
import { useState, useEffect } from 'react'
import { Can, PERM } from '@shared/permissions'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Settings,
  ClipboardList,
  Sparkles,
  Plus,
  Trash2,
  ArrowUp,
  ArrowDown,
  FileCheck,
  CheckCircle,
  Loader2,
  Copy,
  ExternalLink,
  QrCode,
  Lock,
  Download,
  AlertCircle,
  X,
  XCircle,
  Upload,
  Users
} from 'lucide-react'
import { EventApplicantsTab } from './EventApplicantsTab'
import { useAuthStore } from '@features/auth/store/authStore'
import { downloadAuthenticatedFile } from '@services/http/client'
import { registrationApi, RegistrationFormCreate, RegistrationFormField } from '../api/registrationApi'
import { templatesApi } from '../api/templatesApi'
import { eventsAPI } from '../api/eventsApi'
import { useInvitationsList } from '@features/invitations/hooks/useInvitations'
import { getCleanFieldLabel } from '../utils/mappingUtils'
import { createLocalQrDataUrl, LocalQrCode } from '@shared/components/LocalQrCode'
import './event-registration.css'

interface Props {
  event: {
    id: string
    slug: string | null
    title: string
    cover_image_url?: string | null
    title_ar?: string | null
    status: 'draft' | 'published' | 'active' | 'completed' | 'cancelled'
  }
  isActiveTab: boolean
}

export function EventRegistrationTab({ event, isActiveTab }: Props) {
  const tenantId = useAuthStore((s) => s.currentTenantId)
  const eventId = event.id
  const queryClient = useQueryClient()

  // ── Sub-Tabs State ──
  const [activeSubTab, setActiveSubTab] = useState<'form' | 'settings' | 'applicants'>('settings')

  // ── Active Card Focus State ──
  const [activeCardId, setActiveCardId] = useState<string | null>(null)

  // ── Cover Image & Description State ──
  const [coverImageUrl, setCoverImageUrl] = useState('')
  const [isUploadingCover, setIsUploadingCover] = useState(false)
  const [logoUrl, setLogoUrl] = useState('')
  const [isUploadingLogo, setIsUploadingLogo] = useState(false)
  const [welcomeText, setWelcomeText] = useState('')
  const [welcomeTextEn, setWelcomeTextEn] = useState('')

  // ── Local Settings State ──
  const [isEnabled, setIsEnabled] = useState(false)
  const [generationMode, setGenerationMode] = useState<'immediate' | 'deferred'>('immediate')
  const [ticketClass, setTicketClass] = useState<'vip' | 'normal'>('normal')
  const [templateId, setTemplateId] = useState<string>('')
  const [successMessageAr, setSuccessMessageAr] = useState('')
  const [successMessageEn, setSuccessMessageEn] = useState('')
  const [pendingMessageAr, setPendingMessageAr] = useState('')
  const [pendingMessageEn, setPendingMessageEn] = useState('')

  // ── Dynamic Fields State ──
  const [fields, setFields] = useState<RegistrationFormField[]>([
    { id: 'guest_name', type: 'text', label: 'الاسم الكامل', label_en: 'Full Name', required: true, system: true },
    { id: 'guest_phone', type: 'phone', label: 'رقم الجوال', label_en: 'Phone Number', required: true, system: true },
    { id: 'guest_email', type: 'email', label: 'البريد الإلكتروني', label_en: 'Email Address', required: false, system: true },
  ])

  // ── Copy Link Feedback State ──
  const [copied, setCopied] = useState(false)
  const [expiresAt, setExpiresAt] = useState<string>('')

  // Calculate public registration URL
  const registerUrl = `${window.location.origin}/register/${event.slug || ''}`
  const isEventPublic = event.status === 'published' || event.status === 'active'



  // ── Custom Alert State ──
  const [customAlert, setCustomAlert] = useState<{
    show: boolean
    title: string
    message: string
    type: 'success' | 'info' | 'error' | 'warning'
  }>({
    show: false,
    title: '',
    message: '',
    type: 'info'
  })

  const showAlert = (title: string, message: string, type: 'success' | 'info' | 'error' | 'warning' = 'info') => {
    setCustomAlert({
      show: true,
      title,
      message,
      type
    })
  }

  // ── Query List of Applicants for this specific event ──
  const { data: invitations } = useInvitationsList({
    event_id: eventId,
    limit: 500
  })

  // ── Load registration form settings ──
  const { data: formSettings, isLoading: isLoadingForm, refetch: refetchForm } = useQuery({
    queryKey: ['registrationForm', eventId, tenantId],
    queryFn: () => registrationApi.getRegistrationForm(eventId),
    enabled: isActiveTab && !!tenantId,
  })

  // ── Load event templates ──
  const { data: templates } = useQuery({
    queryKey: ['templates', eventId, tenantId],
    queryFn: () => templatesApi.list(eventId),
    enabled: isActiveTab && !!tenantId,
  })

  const { data: eventLogo } = useQuery({
    queryKey: ['event-logo', eventId, tenantId],
    queryFn: () => eventsAPI.getLogo(eventId),
    enabled: isActiveTab && !!tenantId,
  })

  // ── Synchronize state from API ──
  useEffect(() => {
    if (formSettings) {
      setIsEnabled(formSettings.is_enabled)
      setGenerationMode(formSettings.barcode_generation_mode as 'immediate' | 'deferred')
      setTicketClass(formSettings.default_ticket_class as 'vip' | 'normal')
      setTemplateId(formSettings.default_template_id || '')
      setSuccessMessageAr(formSettings.success_message_ar || '')
      setSuccessMessageEn(formSettings.success_message_en || '')
      setPendingMessageAr(formSettings.pending_approval_message_ar || '')
      setPendingMessageEn(formSettings.pending_approval_message_en || '')
      setExpiresAt(formSettings.expires_at ? new Date(formSettings.expires_at).toISOString().slice(0, 16) : '')
      
      const loadedFields = formSettings.fields || []
      const loadedEmailField = loadedFields.find(f => f.id === 'guest_email')

      const systemFields = [
        { id: 'guest_name', type: 'text', label: 'الاسم الكامل', label_en: 'Full Name', required: true, system: true },
        { id: 'guest_phone', type: 'phone', label: 'رقم الجوال', label_en: 'Phone Number', required: true, system: true },
        {
          id: 'guest_email',
          type: 'email',
          label: loadedEmailField?.label || 'البريد الإلكتروني',
          label_en: loadedEmailField?.label_en || 'Email Address',
          required: loadedEmailField ? loadedEmailField.required : false,
          system: true
        },
      ] as RegistrationFormField[]

      // Extract welcome description
      const descField = loadedFields.find(f => f.id === 'cf_welcome_description')
      if (descField) {
        setWelcomeText(descField.label || '')
        setWelcomeTextEn(descField.label_en || '')
      } else {
        setWelcomeText('')
        setWelcomeTextEn('')
      }

      const customFields = loadedFields.filter(f => !f.system && f.id !== 'cf_welcome_description' && f.id !== 'guest_email')
      setFields([...systemFields, ...customFields])
    }
  }, [formSettings])

  useEffect(() => {
    if (event?.cover_image_url) {
      setCoverImageUrl(event.cover_image_url)
    } else {
      setCoverImageUrl('')
    }
  }, [event?.cover_image_url])

  useEffect(() => {
    setLogoUrl(eventLogo?.logo_url || '')
  }, [eventLogo?.logo_url])

  // ── Cover Image Upload Handler ──
  const handleCoverUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setIsUploadingCover(true)
    try {
      const res = await eventsAPI.uploadCover(eventId, file)
      setCoverImageUrl(res.cover_image_url)
      showAlert('تم رفع الصورة بنجاح', 'تم تحديث غلاف النموذج وصورة الحدث بنجاح.', 'success')
      queryClient.invalidateQueries({ queryKey: ['events', tenantId, 'detail', eventId] })
    } catch (err: any) {
      console.error('Failed to upload cover:', err)
      const errorMsg = err.response?.data?.detail || err.message || err
      showAlert('فشل رفع الصورة', `حدث خطأ أثناء رفع الصورة: ${errorMsg}`, 'error')
    } finally {
      setIsUploadingCover(false)
    }
  }

  const handleLogoUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setIsUploadingLogo(true)
    try {
      const res = await eventsAPI.uploadLogo(eventId, file)
      setLogoUrl(res.logo_url)
      queryClient.setQueryData(['event-logo', eventId, tenantId], { logo_url: res.logo_url })
      showAlert('تم حفظ شعار الحفل', 'سيظهر الشعار في نموذج التسجيل وبطاقة الدخول.', 'success')
    } catch (err: any) {
      const errorMsg = err.response?.data?.detail || err.message || err
      showAlert('فشل رفع الشعار', `تعذر حفظ شعار الحفل: ${errorMsg}`, 'error')
    } finally {
      setIsUploadingLogo(false)
      e.target.value = ''
    }
  }

  // ── Copy Link Action ──
  const handleCopyLink = () => {
    navigator.clipboard.writeText(registerUrl)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  // ── QR Download Action ──
  const downloadQrCode = async () => {
    try {
      const qrDataUrl = await createLocalQrDataUrl(registerUrl, 500)
      const link = document.createElement('a')
      link.href = qrDataUrl
      link.download = `QR_تسجيل_${event.title || 'حدث'}.png`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
    } catch {
      showAlert('تعذر توليد رمز QR', 'تعذر توليد رمز التسجيل محلياً. حاول مرة أخرى.', 'error')
    }
  }

  // ── Ticket Class Change Action ──
  const handleTicketClassChange = (newClass: 'vip' | 'normal') => {
    setTicketClass(newClass)
    setTemplateId('') // Reset template selection when ticket class changes
  }

  // ── Template Selection Change Action ──
  const handleTemplateChange = async (newTemplateId: string) => {
    setTemplateId(newTemplateId)
    if (!newTemplateId) return

    try {
      const elements = await templatesApi.getElements(newTemplateId)
      
      const newFields = [...fields]
      let changed = false
      const addedFields: string[] = []

      for (const el of elements) {
        // Skip guest_name since it is a locked system field
        if (el.element_type === 'guest_name') continue

        const isDynamic = el.element_type === 'dynamic_text' && el.data_key
        const isStandardDynamic = ['seat_number', 'gate', 'hall', 'table_number'].includes(el.element_type)

        if (isDynamic || isStandardDynamic) {
          const key = el.data_key || el.element_type
          const cleanLabel = getCleanFieldLabel(key, el.element_type, el.label)

          // Find if this field already exists in registration fields
          const existingIndex = newFields.findIndex(f => f.id === key)

          if (existingIndex > -1) {
            // If it exists, make sure it is required
            if (!newFields[existingIndex].required) {
              newFields[existingIndex] = {
                ...newFields[existingIndex],
                required: true
              }
              changed = true
              addedFields.push(`${cleanLabel} (تحديث إلى إلزامي)`)
            }
          } else {
            // Add new field as required text field
            newFields.push({
              id: key,
              type: 'text',
              label: cleanLabel,
              required: true,
              system: false
            })
            changed = true
            addedFields.push(cleanLabel)
          }
        }
      }

      if (changed) {
        setFields(newFields)
        showAlert(
          'حقول ديناميكية مضافة',
          `تم اكتشاف حقول ديناميكية في القالب المختار وإضافتها تلقائياً كحقول إلزامية في النموذج:\n${addedFields.map(f => '• ' + f).join('\n')}`,
          'success'
        )
      } else {
        showAlert(
          'ربط القالب',
          'تم ربط القالب بنجاح. لم يتم العثور على حقول ديناميكية جديدة لإضافتها أو حقول تحتاج للتحديث.',
          'info'
        )
      }
    } catch (err: any) {
      console.error('Failed to load template elements:', err)
      showAlert('فشل تحميل حقول القالب', `فشل تحميل عناصر القالب: ${err.message || err}`, 'error')
    }
  }

  // ── Save Mutation ──
  const saveMutation = useMutation({
    mutationFn: (data: RegistrationFormCreate) => registrationApi.saveRegistrationForm(eventId, data),
    onSuccess: () => {
      refetchForm()
      queryClient.invalidateQueries({ queryKey: ['events', tenantId, 'detail', eventId] })
      showAlert('تم الحفظ بنجاح', 'تم حفظ إعدادات نموذج التسجيل بنجاح.', 'success')
    },
    onError: (err: any) => {
      showAlert('فشل الحفظ', `فشل حفظ الإعدادات: ${err.message || err}`, 'error')
    }
  })

  const handleSave = async () => {
    try {
      // 1. Update event cover image if changed
      const originalCover = event.cover_image_url || ''
      if (coverImageUrl.trim() !== originalCover) {
        await eventsAPI.update(eventId, { cover_image_url: coverImageUrl.trim() || undefined })
      }

      // 2. Prepend welcome description field to custom fields if provided
      const finalFields = [...fields]
      if (welcomeText.trim()) {
        const descriptionField: RegistrationFormField = {
          id: 'cf_welcome_description',
          type: 'text_block',
          label: welcomeText.trim(),
          label_en: welcomeTextEn.trim() || undefined,
          required: false,
          system: false
        }
        finalFields.unshift(descriptionField)
      }

      const payload: RegistrationFormCreate = {
        is_enabled: isEnabled,
        barcode_generation_mode: generationMode,
        default_ticket_class: ticketClass,
        default_template_id: templateId || null,
        success_message_ar: successMessageAr || null,
        success_message_en: successMessageEn || null,
        pending_approval_message_ar: pendingMessageAr || null,
        pending_approval_message_en: pendingMessageEn || null,
        fields: finalFields,
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
      }
      saveMutation.mutate(payload)
    } catch (err: any) {
      showAlert('فشل الحفظ', `فشل حفظ التعديلات: ${err.message || err}`, 'error')
    }
  }

  // ── Custom Inline Field Handlers ──
  const updateFieldLabel = (id: string, label: string) => {
    setFields(prev => prev.map(f => f.id === id ? { ...f, label } : f))
  }

  const updateFieldLabelEn = (id: string, label_en: string) => {
    setFields(prev => prev.map(f => f.id === id ? { ...f, label_en } : f))
  }

  const updateFieldType = (id: string, type: RegistrationFormField['type']) => {
    setFields(prev => prev.map(f => {
      if (f.id === id) {
        const updated = { ...f, type }
        if (['select', 'multiselect', 'checkbox_group', 'radio_group'].includes(type) && !f.options) {
          updated.options = ['الخيار 1']
        }
        return updated
      }
      return f
    }))
  }

  const toggleFieldRequired = (id: string) => {
    setFields(prev => prev.map(f => {
      if (f.id === id) {
        return { ...f, required: !f.required }
      }
      return f
    }))
  }

  const removeField = (id: string) => {
    setFields(prev => prev.filter(f => f.id !== id))
  }

  const moveField = (index: number, direction: 'up' | 'down') => {
    if (direction === 'up' && index === 0) return
    if (direction === 'down' && index === fields.length - 1) return

    const newFields = [...fields]
    const swapTarget = direction === 'up' ? index - 1 : index + 1
    const temp = newFields[index]
    newFields[index] = newFields[swapTarget]
    newFields[swapTarget] = temp
    setFields(newFields)
  }

  const addOptionToField = (id: string) => {
    setFields(prev => prev.map(f => {
      if (f.id === id) {
        const opts = f.options || []
        return { ...f, options: [...opts, `الخيار ${opts.length + 1}`] }
      }
      return f
    }))
  }

  const removeOptionFromField = (id: string, optionIndex: number) => {
    setFields(prev => prev.map(f => {
      if (f.id === id && f.options) {
        return { ...f, options: f.options.filter((_, idx) => idx !== optionIndex) }
      }
      return f
    }))
  }

  const updateOptionInField = (id: string, optionIndex: number, newValue: string) => {
    setFields(prev => prev.map(f => {
      if (f.id === id && f.options) {
        const updatedOpts = [...f.options]
        updatedOpts[optionIndex] = newValue
        return { ...f, options: updatedOpts }
      }
      return f
    }))
  }

  const addCustomField = () => {
    const newId = `cf_${Date.now()}`
    const newField: RegistrationFormField = {
      id: newId,
      type: 'text',
      label: 'سؤال جديد',
      label_en: 'New Question',
      required: false,
      system: false
    }
    setFields(prev => [...prev, newField])
  }

  if (!isActiveTab) return null

  if (isLoadingForm) {
    return (
      <div className="event-reg-loading">
        <Loader2 className="spin" size={32} />
        <p>جاري تحميل إعدادات نموذج التسجيل...</p>
      </div>
    )
  }

  return (
    <div className="event-registration-tab-overhaul" dir="rtl">
      
      {/* ── SECTION HEADER & PUBLIC URL SHARING PANEL ── */}
      <div className="premium-sharing-header glass-panel">
        <div className="header-text-block">
          <div className="badge-row">
            <span className={`status-badge-glow ${isEnabled && isEventPublic ? 'enabled' : 'disabled'}`}>
              ● {isEnabled ? (isEventPublic ? 'النموذج نشط ومتاح للعامة' : 'النموذج مفعّل — انشر الحدث لإتاحة الرابط') : 'التسجيل مغلق'}
            </span>
          </div>
          <h2>رابط تسجيل الحضور العام</h2>
          <p>شارك الرابط أو رمز الـ QR أدناه مع ضيوفك ليتمكنوا من حجز مقاعدهم وتسجيل حضورهم ذاتياً.</p>
          
          <div className="premium-link-bar">
            <input type="text" readOnly value={registerUrl} className="share-url-input" />
            <button className={`share-action-btn copy-btn ${copied ? 'copied' : ''}`} onClick={handleCopyLink} disabled={!isEventPublic}>
              <Copy size={15} />
              <span>{copied ? 'تم النسخ!' : 'نسخ الرابط'}</span>
            </button>
            <a href={isEventPublic ? registerUrl : undefined} onClick={(e) => { if (!isEventPublic) e.preventDefault() }} aria-disabled={!isEventPublic} target="_blank" rel="noreferrer" className="share-action-btn preview-btn">
              <ExternalLink size={15} />
              <span>معاينة الصفحة</span>
            </a>
            <button
              onClick={() => setActiveSubTab('applicants')}
              className="share-action-btn copy-btn"
              style={{ background: 'linear-gradient(135deg, #C9A96E 0%, #b08b47 100%)', color: '#0f172a', fontWeight: 'bold' }}
            >
              <ClipboardList size={15} />
              <span>استعراض المسجلين ({invitations?.filter(inv => !!inv.is_registration && ['pending', 'accepted', 'declined'].includes(inv.rsvp_status || '')).length || 0})</span>
            </button>
          </div>
        </div>
        
        {/* Interactive QR Block */}
        <div className="premium-qr-block" onClick={() => { if (isEventPublic) void downloadQrCode() }} title={isEventPublic ? 'اضغط لتحميل كود QR' : 'انشر الحدث أولاً'} style={{ opacity: isEventPublic ? 1 : 0.45, cursor: isEventPublic ? 'pointer' : 'not-allowed' }}>
          <div className="qr-image-wrapper">
            <LocalQrCode value={registerUrl} size={150} alt="QR Code" />
            <div className="qr-hover-overlay">
              <Download size={18} />
              <span>تحميل QR</span>
            </div>
          </div>
          <span className="qr-subtext"><QrCode size={12} /> اضغط لحفظ الرمز</span>
        </div>
      </div>

      {expiresAt && new Date(expiresAt) < new Date() && (
        <div className="premium-sharing-header glass-panel" style={{ border: '1px solid rgba(239, 68, 68, 0.2)', background: 'rgba(239, 68, 68, 0.05)', marginTop: '-12px', display: 'flex', gap: 20 }}>
          <div className="header-text-block" style={{ flex: 1 }}>
            <h3 style={{ color: '#ef4444', display: 'flex', alignItems: 'center', gap: 8, fontSize: '1.2rem', fontWeight: 'bold' }}>
              <XCircle size={18} />
              <span>انتهى وقت التسجيل المخصص لهذا الحدث</span>
            </h3>
            <p style={{ marginTop: 6, fontSize: '0.9rem', color: '#94a3b8' }}>لقد تجاوز تاريخ انتهاء التسجيل ({new Date(expiresAt).toLocaleString('ar-SA')}). يمكنك الآن تنزيل كافة الدعوات والبطاقات المقبولة دفعة واحدة للطباعة أو الأرشفة:</p>
            <div className="premium-link-bar" style={{ marginTop: 16, display: 'flex', gap: 12 }}>
              <a
                href="#"
                onClick={(e) => { e.preventDefault(); void downloadAuthenticatedFile(`/fast-invitations/history/${eventId}/registration_submissions/pdf`, 'registration-submissions.pdf') }}
                target="_blank"
                rel="noreferrer"
                className="share-action-btn preview-btn"
                style={{ background: 'rgba(16, 185, 129, 0.1)', border: '1px solid rgba(16, 185, 129, 0.2)', color: '#10b981', display: 'inline-flex', padding: '8px 16px', borderRadius: '6px', fontSize: '0.85rem', textDecoration: 'none', alignItems: 'center', gap: 6 }}
              >
                <Download size={14} />
                <span>تنزيل كافة الدعوات (PDF)</span>
              </a>
              <a
                href="#"
                onClick={(e) => { e.preventDefault(); void downloadAuthenticatedFile(`/fast-invitations/history/${eventId}/registration_submissions/zip`, 'registration-submissions.zip') }}
                target="_blank"
                rel="noreferrer"
                className="share-action-btn preview-btn"
                style={{ background: 'rgba(59, 130, 246, 0.1)', border: '1px solid rgba(59, 130, 246, 0.2)', color: '#3b82f6', display: 'inline-flex', padding: '8px 16px', borderRadius: '6px', fontSize: '0.85rem', textDecoration: 'none', alignItems: 'center', gap: 6 }}
              >
                <Download size={14} />
                <span>تنزيل أرشيف الصور (ZIP)</span>
              </a>
            </div>
          </div>
        </div>
      )}



      {/* ── SUB-TABS NAVIGATION BAR ── */}
      <div className="registration-subtabs-nav glass-panel">
        <button
          className={`subtab-btn ${activeSubTab === 'settings' ? 'active' : ''}`}
          onClick={() => setActiveSubTab('settings')}
        >
          <Settings size={16} />
          <span>⚙️ إعدادات التذاكر والقبول</span>
        </button>
        <button
          className={`subtab-btn ${activeSubTab === 'form' ? 'active' : ''}`}
          onClick={() => setActiveSubTab('form')}
        >
          <ClipboardList size={16} />
          <span>📝 نموذج وأسئلة التسجيل</span>
        </button>
        <button
          className={`subtab-btn ${activeSubTab === 'applicants' ? 'active' : ''}`}
          onClick={() => setActiveSubTab('applicants')}
        >
          <Users size={16} />
          <span>👥 المسجلين ({invitations?.filter(inv => !!inv.is_registration && ['pending', 'accepted', 'declined'].includes(inv.rsvp_status || '')).length || 0})</span>
        </button>
      </div>

      {/* ── SUB-TABS CONTENT PANELS ── */}
      {activeSubTab === 'form' && (
        <div className="google-forms-builder-tab animated-fade">
          <div className="google-forms-editor-canvas">
            
            {/* 1. Cover Image Card */}
            <div className="google-form-cover-card">
              <div className="cover-image-url-input-block">
                <label>شعار الحفل</label>
                {logoUrl && (
                  <div style={{ display: 'flex', justifyContent: 'center', padding: '14px 0' }}>
                    <img src={logoUrl} alt="شعار الحفل" style={{ maxWidth: 180, maxHeight: 110, objectFit: 'contain' }} />
                  </div>
                )}
                <div className="cover-image-upload-wrapper">
                  <label className="cover-upload-dropzone">
                    {isUploadingLogo ? (
                      <div className="upload-loading-spinner">
                        <Loader2 className="spin" size={24} />
                        <span>جاري رفع الشعار...</span>
                      </div>
                    ) : (
                      <>
                        <Upload size={20} />
                        <span>{logoUrl ? 'استبدال شعار الحفل' : 'رفع شعار الحفل'} (PNG, JPG, WEBP)</span>
                      </>
                    )}
                    <input
                      type="file"
                      accept="image/png,image/jpeg,image/webp"
                      onChange={handleLogoUpload}
                      disabled={isUploadingLogo}
                      style={{ display: 'none' }}
                    />
                  </label>
                </div>
                <small style={{ display: 'block', marginTop: 8, opacity: 0.7 }}>
                  يفضل شعار بخلفية شفافة وأبعاد مربعة أو أفقية.
                </small>
              </div>

              {coverImageUrl ? (
                <div className="google-form-cover-image-container">
                  <img src={coverImageUrl} alt="Cover Banner" className="google-form-cover-image" />
                  <div className="google-form-cover-actions">
                    <button className="btn-cover-action-delete" onClick={() => setCoverImageUrl('')}>
                      حذف صورة الغلاف 🗑️
                    </button>
                  </div>
                </div>
              ) : null}
              
              <div className="cover-image-url-input-block">
                <label>صورة غلاف نموذج التسجيل (Banner Image)</label>
                
                <div className="cover-image-upload-wrapper">
                  <label className="cover-upload-dropzone">
                    {isUploadingCover ? (
                      <div className="upload-loading-spinner">
                        <Loader2 className="spin" size={24} />
                        <span>جاري رفع الصورة...</span>
                      </div>
                    ) : (
                      <>
                        <Upload size={20} />
                        <span>اضغط لرفع صورة من جهازك (PNG, JPG, WEBP)</span>
                      </>
                    )}
                    <input
                      type="file"
                      accept="image/*"
                      onChange={handleCoverUpload}
                      disabled={isUploadingCover}
                      style={{ display: 'none' }}
                    />
                  </label>
                </div>

                <div className="cover-or-divider">أو ضع رابط صورة مباشر</div>

                <div className="cover-url-manual-input">
                  <input
                    type="text"
                    className="premium-select-input ltr-input"
                    placeholder="أدخل رابط صورة الغلاف https://example.com/banner-image.png"
                    value={coverImageUrl}
                    onChange={(e) => setCoverImageUrl(e.target.value)}
                  />
                </div>
              </div>
            </div>

            {/* 2. Form Title and Description Card */}
            <div className="google-form-header-card">
              <div className="google-form-purple-strip"></div>
              
              <div className="google-form-title-display">
                <h2>{event.title_ar || event.title}</h2>
                <span className="google-form-title-helper">اسم الفعالية الأساسي (يمكنك تغييره من إعدادات الحدث)</span>
              </div>

              <div className="google-form-description-inputs">
                <div className="settings-field-group">
                  <label>رسالة الترحيب / وصف النموذج باللغة العربية</label>
                  <textarea
                    rows={3}
                    className="google-form-description-input"
                    placeholder="اكتب نبذة ترحيبية بالضيوف أو تعليمات التسجيل هنا..."
                    value={welcomeText}
                    onChange={(e) => setWelcomeText(e.target.value)}
                  />
                </div>
                
                <div className="settings-field-group">
                  <label>Welcome Description (English - Optional)</label>
                  <textarea
                    rows={2}
                    className="google-form-description-input ltr-input"
                    placeholder="Form welcome description or guidelines in English..."
                    value={welcomeTextEn}
                    onChange={(e) => setWelcomeTextEn(e.target.value)}
                  />
                </div>
              </div>
            </div>

            {/* 3. Dynamic Question Cards */}
            <div className="google-form-questions-stack">
              {fields.map((field, index) => {
                const isActive = activeCardId === field.id;
                
                return (
                  <div
                    key={field.id}
                    className={`google-form-question-card ${isActive ? 'active-card' : ''} ${field.system ? 'system-card' : ''}`}
                    onClick={() => setActiveCardId(field.id)}
                  >
                    <div className="question-card-header">
                      <div className="question-inputs-block">
                        {/* Arabic Label */}
                        <div className="question-input-wrapper">
                          <span className="lang-label">AR</span>
                          <input
                            type="text"
                            value={field.label}
                            onChange={(e) => updateFieldLabel(field.id, e.target.value)}
                            placeholder="السؤال باللغة العربية *"
                            disabled={field.system}
                            className="google-question-title-input"
                          />
                        </div>

                        {/* English Label */}
                        <div className="question-input-wrapper">
                          <span className="lang-label text-blue">EN</span>
                          <input
                            type="text"
                            value={field.label_en || ''}
                            onChange={(e) => updateFieldLabelEn(field.id, e.target.value)}
                            placeholder="Question in English (Optional)"
                            disabled={field.system}
                            className="google-question-title-input ltr-input"
                          />
                        </div>
                      </div>

                      {/* Question Type Selector */}
                      <select
                        value={field.type}
                        onChange={(e) => updateFieldType(field.id, e.target.value as any)}
                        disabled={field.system}
                        className="google-question-type-select"
                      >
                        <option value="text">🔤 نص قصير (Text)</option>
                        <option value="number">🔢 حقل رقمي (Number)</option>
                        <option value="email">📧 بريد إلكتروني (Email)</option>
                        <option value="phone">📞 رقم هاتف (Phone)</option>
                        <option value="select">🔽 قائمة خيارات منسدلة (Dropdown Select)</option>
                        <option value="multiselect">🗂️ خيارات متعددة (Multi-select Dropdown)</option>
                        <option value="checkbox_group">☑️ مجموعة مربعات تحديد (Checkbox Group)</option>
                        <option value="radio_group">🔘 أزرار خيار مفرد (Radio Buttons)</option>
                        <option value="date">📅 حقل تاريخ (Date)</option>
                        <option value="checkbox">☑️ موافقة (Single Checkbox)</option>
                      </select>
                    </div>

                    {/* Question Content Body */}
                    {['select', 'multiselect', 'checkbox_group', 'radio_group'].includes(field.type) && (
                      <div className="google-question-body">
                        <div className="google-options-list">
                          {field.options?.map((opt, optIdx) => (
                            <div key={optIdx} className="google-option-row">
                              <div className={field.type === 'radio_group' ? "google-radio-indicator" : "google-checkbox-indicator"}></div>
                              <input
                                type="text"
                                value={opt}
                                onChange={(e) => updateOptionInField(field.id, optIdx, e.target.value)}
                                placeholder={`الخيار ${optIdx + 1}`}
                                className="google-option-value-input"
                              />
                              {field.options && field.options.length > 1 && (
                                <button
                                  type="button"
                                  className="btn-delete-option-inline"
                                  onClick={(e) => { e.stopPropagation(); removeOptionFromField(field.id, optIdx); }}
                                  title="حذف الخيار"
                                >
                                  <X size={14} />
                                </button>
                              )}
                            </div>
                          ))}
                          <button
                            type="button"
                            className="btn-add-option-inline"
                            onClick={(e) => { e.stopPropagation(); addOptionToField(field.id); }}
                          >
                            <Plus size={12} />
                            <span>إضافة خيار جديد</span>
                          </button>
                        </div>
                      </div>
                    )}

                    {/* Question Card Action Footer */}
                    <div className="google-question-card-footer">
                      <div className="footer-actions-left">
                        {/* Reordering */}
                        <button
                          type="button"
                          className="btn-footer-card-action"
                          disabled={index === 0}
                          onClick={(e) => { e.stopPropagation(); moveField(index, 'up'); }}
                          title="نقل للأعلى"
                        >
                          <ArrowUp size={14} />
                        </button>
                        <button
                          type="button"
                          className="btn-footer-card-action"
                          disabled={index === fields.length - 1}
                          onClick={(e) => { e.stopPropagation(); moveField(index, 'down'); }}
                          title="نقل للأسفل"
                        >
                          <ArrowDown size={14} />
                        </button>

                        <div className="divider-vertical"></div>

                        {/* Delete */}
                        {!field.system ? (
                          <button
                            type="button"
                            className="btn-footer-card-action btn-delete-danger"
                            onClick={(e) => { e.stopPropagation(); removeField(field.id); }}
                            title="حذف السؤال"
                          >
                            <Trash2 size={14} />
                          </button>
                        ) : (
                          <span className="locked-badge-indicator"><Lock size={10} /> سؤال أساسي مغلق</span>
                        )}
                      </div>

                      <div className="footer-actions-right">
                        <label className="google-required-toggle" onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            checked={field.required}
                            disabled={field.id === 'guest_name' || field.id === 'guest_phone'}
                            onChange={() => toggleFieldRequired(field.id)}
                          />
                          <span>مطلوب إلزامي</span>
                        </label>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* 4. Add Question Button */}
            <button type="button" className="btn-add-question-google" onClick={addCustomField}>
              <Plus size={16} />
              <span>إضافة سؤال مخصص للنموذج</span>
            </button>

          </div>
        </div>
      )}

      {activeSubTab === 'settings' && (
        <div className="subtab-content-panel animated-fade">
          <div className="registration-grid-overhaul-single">
            <div className="config-settings-column-full">
              
              {/* Main Activation Card */}
              <div className="premium-settings-card glass-panel">
                <div className="card-header-toggle">
                  <div className="header-title">
                    <Settings size={18} />
                    <h3>حالة وإعدادات التفعيل</h3>
                  </div>
                  <div className="modern-switch-wrapper">
                    <button
                      className={`modern-switch-toggle ${isEnabled ? 'on' : 'off'}`}
                      onClick={() => setIsEnabled(!isEnabled)}
                    >
                      <span className="modern-switch-slider"></span>
                    </button>
                  </div>
                </div>
                
                <div className="settings-field-group">
                  <label>آلية توليد وإصدار التذاكر</label>
                  <div className="mode-selection-cards">
                    
                    <div
                      className={`mode-card-premium ${generationMode === 'immediate' ? 'active-immediate' : ''}`}
                      onClick={() => setGenerationMode('immediate')}
                    >
                      <div className="mode-card-header">
                        <CheckCircle className="mode-icon" size={18} />
                        <h4>إصدار فوري ومباشر</h4>
                      </div>
                      <p>توليد باركود تذكرة الدخول وإرسالها فورياً للضيف بمجرد إرسال النموذج بنجاح.</p>
                    </div>

                    <div
                      className={`mode-card-premium ${generationMode === 'deferred' ? 'active-deferred' : ''}`}
                      onClick={() => setGenerationMode('deferred')}
                    >
                      <div className="mode-card-header">
                        <FileCheck className="mode-icon" size={18} />
                        <h4>مراجعة وقبول المنظم</h4>
                      </div>
                      <p>حفظ الطلب كـ "قيد الانتظار". لا يتم توليد باركود التذكرة إلا بعد قبول الطلب يدوياً.</p>
                    </div>

                  </div>
                </div>

                <div className="dropdowns-split-row">
                  <div className="settings-field-group">
                    <label>الفئة الافتراضية للبطاقة</label>
                    <select
                      className="premium-select-input"
                      value={ticketClass}
                      onChange={(e) => handleTicketClassChange(e.target.value as 'vip' | 'normal')}
                    >
                      <option value="normal">🎫 عادي (Normal)</option>
                      <option value="vip">👑 VIP</option>
                    </select>
                  </div>

                  <div className="settings-field-group">
                    <label>قالب كرت الدعوة</label>
                    <select
                      className="premium-select-input"
                      value={templateId}
                      onChange={(e) => handleTemplateChange(e.target.value)}
                    >
                      <option value="">باركود فقط (تذكرة افتراضية)</option>
                      {templates
                        ?.filter((t: any) => (t.ticket_class || 'normal') === ticketClass)
                        .map((t: any) => (
                          <option key={t.id} value={t.id}>
                            {t.name} ({t.template_type === 'designed' ? 'كرت مصمم' : 'سريع'})
                          </option>
                        ))}
                    </select>
                  </div>
                </div>

                <div className="dropdowns-split-row" style={{ marginTop: '16px' }}>
                  <div className="settings-field-group">
                    <label>📅 تاريخ ووقت انتهاء التسجيل (تلقائي)</label>
                    <input
                      type="datetime-local"
                      className="premium-select-input"
                      value={expiresAt}
                      onChange={(e) => setExpiresAt(e.target.value)}
                      style={{ colorScheme: 'dark' }}
                    />
                  </div>
                  <div className="settings-field-group">
                    {/* Empty placeholder */}
                  </div>
                </div>
              </div>

              {/* Feedback Messages Card */}
              <div className="premium-settings-card glass-panel">
                <div className="header-title">
                  <ClipboardList size={18} />
                  <h3>رسائل تأكيد التسجيل للضيوف</h3>
                </div>
                
                {generationMode === 'immediate' ? (
                  <div className="messages-textareas-grid">
                    <div className="settings-field-group">
                      <label>رسالة النجاح باللغة العربية (الفوري)</label>
                      <textarea
                        rows={3}
                        className="premium-textarea"
                        placeholder="مثال: تم تسجيلكم بنجاح! يمكنك تحميل بطاقة الدخول الخاصة بك الآن."
                        value={successMessageAr}
                        onChange={(e) => setSuccessMessageAr(e.target.value)}
                      />
                    </div>
                    <div className="settings-field-group">
                      <label>رسالة النجاح باللغة الإنجليزية (الفوري)</label>
                      <textarea
                        rows={3}
                        className="premium-textarea ltr-input"
                        placeholder="e.g. Registration successful! You can download your invitation card now."
                        value={successMessageEn}
                        onChange={(e) => setSuccessMessageEn(e.target.value)}
                      />
                    </div>
                  </div>
                ) : (
                  <div className="messages-textareas-grid">
                    <div className="settings-field-group">
                      <label>رسالة قيد المراجعة باللغة العربية (المؤجل)</label>
                      <textarea
                        rows={3}
                        className="premium-textarea"
                        placeholder="مثال: تم استلام طلبكم بنجاح وهو قيد المراجعة حالياً، وسيتم إرسال بطاقة الدخول فور الموافقة."
                        value={pendingMessageAr}
                        onChange={(e) => setPendingMessageAr(e.target.value)}
                      />
                    </div>
                    <div className="settings-field-group">
                      <label>رسالة قيد المراجعة باللغة الإنجليزية (المؤجل)</label>
                      <textarea
                        rows={3}
                        className="premium-textarea ltr-input"
                        placeholder="e.g. Request received! It is under review and you will receive your invitation card upon approval."
                        value={pendingMessageEn}
                        onChange={(e) => setPendingMessageEn(e.target.value)}
                      />
                    </div>
                  </div>
                )}
              </div>

            </div>
          </div>
        </div>
      )}

      {activeSubTab === 'applicants' && (
        <EventApplicantsTab eventId={eventId} eventTitle={event.title} isActiveTab={activeSubTab === 'applicants'} />
      )}

      {/* ── FLOATING SAVE BAR ── */}
      {activeSubTab !== 'applicants' && (
        <div className="premium-floating-save-bar glass-panel">
          <div className="info-badge">
            <AlertCircle size={14} />
            <span>تأكد من حفظ التعديلات لتطبيقها على صفحة التسجيل العامة للضيوف.</span>
          </div>
          <Can permission={PERM.REG_MANAGE}>
            <button
              className="btn-save-premium-glow"
              onClick={handleSave}
              disabled={saveMutation.isPending}
            >
              {saveMutation.isPending ? (
                <>
                  <Loader2 className="spin" size={16} />
                  جاري حفظ الإعدادات...
                </>
              ) : (
                <>
                  <Sparkles size={16} />
                  حفظ التعديلات والتفعيل
                </>
              )}
            </button>
          </Can>
        </div>
      )}



      {/* ── CUSTOM PREMIUM ALERT MODAL ── */}
      {customAlert.show && (
        <div className="custom-alert-overlay" onClick={() => setCustomAlert(prev => ({ ...prev, show: false }))}>
          <div className={`custom-alert-panel ${customAlert.type}`} onClick={(e) => e.stopPropagation()}>
            <div className={`custom-alert-icon-wrapper ${customAlert.type}`}>
              {customAlert.type === 'success' && <CheckCircle size={28} />}
              {customAlert.type === 'error' && <XCircle size={28} />}
              {customAlert.type === 'warning' && <AlertCircle size={28} />}
              {customAlert.type === 'info' && <Sparkles size={28} />}
            </div>
            <h4 className="custom-alert-title">{customAlert.title}</h4>
            <p className="custom-alert-message">{customAlert.message}</p>
            <button 
              className="btn-custom-alert-close"
              onClick={() => setCustomAlert(prev => ({ ...prev, show: false }))}
            >
              موافق
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
