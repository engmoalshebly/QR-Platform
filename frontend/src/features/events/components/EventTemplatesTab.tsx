/**
 * EventTemplatesTab.tsx
 * إدارة القوالب المخصصة للمناسبة - إضافة، معاينة، حذف
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import http from '@services/http/client'
import { Plus, Eye, Trash2, Download, AlertCircle, Loader2, Pencil } from 'lucide-react'
import { useAuthStore } from '@features/auth/store/authStore'
import { templatesApi } from '@features/events/api/templatesApi'
import './EventTemplatesTab.css'
import { Can, PERM } from '@shared/permissions'

interface EventTemplatesTabProps {
  eventId: string
  event: any
  isActiveTab: boolean
}

export function EventTemplatesTab({ eventId, event, isActiveTab }: EventTemplatesTabProps) {
  const navigate = useNavigate()
  const [selectedTemplate, setSelectedTemplate] = useState<any>(null)
  const [showPreviewModal, setShowPreviewModal] = useState(false)
  const [activePreviewFields, setActivePreviewFields] = useState<any[]>([])
  const [previewData, setPreviewData] = useState<any>({
    guest_name: 'أحمد علي',
    guest_phone: '',
    guest_email: '',
    guest_company: '',
    guest_title: '',
    event_title: 'حفل تخرج',
    event_date: '2025-06-15',
    event_time: '19:00',
    event_location: 'فندق الريتز',
    seat_number: 'A12',
    table_number: '5',
    custom_data: {},
  })

  const tenantId = useAuthStore((s) => s.currentTenantId)

  // Helper functions for field detection
  const mapElementToField = (el: any) => {
    const etype = el.element_type
    const dk = el.data_key || ''

    if (etype === 'guest_name') {
      return { key: 'guest_name', label: 'اسم الضيف', type: 'text', defaultValue: 'أحمد علي' }
    }
    if (etype === 'event_title') {
      return { key: 'event_title', label: 'عنوان الحفل', type: 'text', defaultValue: event?.title || 'حفل تخرج' }
    }
    if (etype === 'event_date') {
      const parts = event?.start_date?.split('T') || []
      return { key: 'event_date', label: 'تاريخ الحفل', type: 'date', defaultValue: parts[0] || '2025-06-15' }
    }
    if (etype === 'event_time') {
      const parts = event?.start_date?.split('T') || []
      const defaultTime = parts[1] ? parts[1].substring(0, 5) : '19:00'
      return { key: 'event_time', label: 'وقت الحفل', type: 'time', defaultValue: defaultTime }
    }
    if (etype === 'event_location') {
      return { key: 'event_location', label: 'مكان الحفل', type: 'text', defaultValue: event?.venue_name || 'فندق الريتز' }
    }
    if (etype === 'seat_number') {
      return { key: 'seat_number', label: 'رقم المقعد', type: 'text', defaultValue: 'A12' }
    }
    if (etype === 'table_number') {
      return { key: 'table_number', label: 'رقم الطاولة', type: 'text', defaultValue: '5' }
    }
    if (etype === 'gate') {
      return { key: 'gate', label: 'البوابة', type: 'text', defaultValue: 'البوابة الرئيسية', isCustomData: true, customKey: 'gate' }
    }
    if (etype === 'hall') {
      return { key: 'hall', label: 'القاعة', type: 'text', defaultValue: 'القاعة الكبرى', isCustomData: true, customKey: 'hall' }
    }

    if (etype === 'dynamic_text' && dk) {
      const keyNorm = dk.trim().toLowerCase()
      
      if (['guest.name', 'guest.name_ar', 'guest_name', 'name', 'الاسم', 'اسم الضيف', 'guestname', 'اسم_الضيف'].includes(keyNorm)) {
        return { key: 'guest_name', label: 'اسم الضيف', type: 'text', defaultValue: 'أحمد علي' }
      }
      if (['guest.phone', 'guest_phone', 'phone', 'الجوال', 'رقم الجوال', 'رقم الهاتف', 'الهاتف'].includes(keyNorm)) {
        return { key: 'guest_phone', label: 'رقم الجوال', type: 'text', defaultValue: '0500000000' }
      }
      if (['guest.email', 'guest_email', 'email', 'البريد', 'البريد الإلكتروني'].includes(keyNorm)) {
        return { key: 'guest_email', label: 'البريد الإلكتروني', type: 'text', defaultValue: 'guest@example.com' }
      }
      if (['guest.company', 'guest_company', 'company', 'الجهة', 'الجهة / الشركة', 'الشركة', 'جهة العمل'].includes(keyNorm)) {
        return { key: 'guest_company', label: 'الجهة / الشركة', type: 'text', defaultValue: 'شركة التقنية' }
      }
      if (['guest.title', 'guest_title', 'title', 'المسمى الوظيفي', 'المنصب'].includes(keyNorm)) {
        return { key: 'guest_title', label: 'المسمى الوظيفي', type: 'text', defaultValue: 'مدير عام' }
      }
      if (['event.title', 'event.title_ar', 'event_title', 'title', 'العنوان', 'اسم الفعالية', 'عنوان الفعالية'].includes(keyNorm)) {
        return { key: 'event_title', label: 'عنوان الحفل', type: 'text', defaultValue: event?.title || 'حفل تخرج' }
      }
      if (['event.date', 'event_date', 'date', 'التاريخ', 'تاريخ', 'تاريخ الفعالية'].includes(keyNorm)) {
        const parts = event?.start_date?.split('T') || []
        return { key: 'event_date', label: 'تاريخ الحفل', type: 'date', defaultValue: parts[0] || '2025-06-15' }
      }
      if (['event.time', 'event_time', 'time', 'الوقت', 'وقت', 'وقت الفعالية'].includes(keyNorm)) {
        const parts = event?.start_date?.split('T') || []
        const defaultTime = parts[1] ? parts[1].substring(0, 5) : '19:00'
        return { key: 'event_time', label: 'وقت الحفل', type: 'time', defaultValue: defaultTime }
      }
      if (['event.location', 'event.location_ar', 'event_location', 'location', 'المكان', 'الموقع', 'venue'].includes(keyNorm)) {
        return { key: 'event_location', label: 'مكان الحفل', type: 'text', defaultValue: event?.venue_name || 'فندق الريتز' }
      }
      if (['custom.seat', 'seat_number', 'seat', 'رقم المقعد', 'المقعد'].includes(keyNorm)) {
        return { key: 'seat_number', label: 'رقم المقعد', type: 'text', defaultValue: 'A12' }
      }
      if (['custom.table', 'table_number', 'table', 'الطاولة', 'رقم الطاولة'].includes(keyNorm)) {
        return { key: 'table_number', label: 'رقم الطاولة', type: 'text', defaultValue: '5' }
      }
      if (['custom.gate', 'gate', 'البوابة', 'بوابة'].includes(keyNorm)) {
        return { key: 'gate', label: 'البوابة', type: 'text', defaultValue: 'البوابة الرئيسية', isCustomData: true, customKey: 'gate' }
      }
      if (['custom.hall', 'hall', 'القاعة', 'قاعة'].includes(keyNorm)) {
        return { key: 'hall', label: 'القاعة', type: 'text', defaultValue: 'القاعة الكبرى', isCustomData: true, customKey: 'hall' }
      }

      const cleanKey = dk.startsWith('custom.') ? dk.substring(7) : dk
      const fieldLabel = el.label || cleanKey
      return {
        key: `custom_data.${cleanKey}`,
        label: fieldLabel,
        type: 'text',
        defaultValue: `بيانات ${fieldLabel}`,
        isCustomData: true,
        customKey: cleanKey
      }
    }
    return null
  }

  const detectFields = (elements: any[]) => {
    const fieldsMap = new Map<string, any>()
    for (const el of elements) {
      const field = mapElementToField(el)
      if (field && !fieldsMap.has(field.key)) {
        fieldsMap.set(field.key, field)
      }
    }
    return Array.from(fieldsMap.values())
  }

  // جلب القوالب الخاصة بالمناسبة
  const { data: templates, isLoading, refetch } = useQuery({
    queryKey: ['templates', eventId, tenantId],
    queryFn: async () => {
      if (!isActiveTab || !tenantId) return []
      return templatesApi.list(eventId)
    },
    enabled: isActiveTab && !!tenantId,
  })

  // حذف القالب
  const deleteMutation = useMutation({
    mutationFn: async (templateId: string) => {
      await http.delete(`/templates/${templateId}`)
    },
    onSuccess: () => {
      refetch()
    },
  })

  // معاينة القالب
  const previewMutation = useMutation({
    mutationFn: async ({ templateId, data }: { templateId: string; data: any }) => {
      const response = await http.post(
        `/templates/${templateId}/preview`,
        data,
        {
          responseType: 'blob',
        }
      )
      return URL.createObjectURL(response.data)
    },
  })

  const handlePreview = async (template: any) => {
    setSelectedTemplate(template)
    try {
      const elements = await templatesApi.getElements(template.id)
      const fields = detectFields(elements)
      setActivePreviewFields(fields)

      const initialData: any = {
        guest_name: '',
        guest_phone: '',
        guest_email: '',
        guest_company: '',
        guest_title: '',
        event_title: '',
        event_date: '',
        event_time: '',
        event_location: '',
        seat_number: '',
        table_number: '',
        custom_data: {},
      }

      fields.forEach((f) => {
        if (f.isCustomData) {
          initialData.custom_data[f.customKey] = f.defaultValue
        } else {
          initialData[f.key] = f.defaultValue
        }
      })

      setPreviewData(initialData)
      setShowPreviewModal(true)
      await previewMutation.mutateAsync({ templateId: template.id, data: initialData })
    } catch (err) {
      console.error('Failed to load preview:', err)
      alert('فشل تحميل تفاصيل القالب للمعاينة')
    }
  }

  const handleDelete = (template: any) => {
    if (window.confirm(`هل أنت متأكد من حذف القالب "${template.name}"؟`)) {
      deleteMutation.mutate(template.id)
    }
  }

  const handleDownloadPreview = async () => {
    if (!selectedTemplate) return
    try {
      const response = await http.post(
        `/templates/${selectedTemplate.id}/preview`,
        previewData,
        {
          responseType: 'blob',
        }
      )
      const blob = response.data
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `preview_${selectedTemplate.name || 'template'}.png`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(url)
    } catch (err) {
      console.error('Failed to download preview image:', err)
      alert('فشل تحميل المعاينة')
    }
  }

  if (isLoading) {
    return (
      <div className="event-templates-loading">
        <Loader2 size={32} className="spin" />
        <p>جاري تحميل القوالب...</p>
      </div>
    )
  }

  return (
    <div className="event-templates-tab">
      {/* Header */}
      <div className="templates-header">
        <div>
          <h2>قوالب المناسبة</h2>
          <p className="templates-subtitle">
            إدارة القوالب المخصصة للدعوات - إضافة، معاينة، وحذف
          </p>
        </div>
        <Can permission={PERM.TMPL_CREATE}>
          <button className="btn btn-primary" onClick={() => navigate(`/events/${eventId}/design?mode=excel`)}>
            <Plus size={16} />
            قالب جديد
          </button>
        </Can>
      </div>

      {/* Templates Grid */}
      {!templates || templates.length === 0 ? (
        <div className="templates-empty-state">
          <AlertCircle size={48} />
          <h3>لا توجد قوالب</h3>
          <p>أنشئ قالب جديد لبدء تخصيص دعوات المناسبة</p>
          <Can permission={PERM.TMPL_CREATE}>
            <button className="btn btn-primary" onClick={() => navigate(`/events/${eventId}/design?mode=excel`)}>
              <Plus size={16} />
              إنشاء قالب جديد
            </button>
          </Can>
        </div>
      ) : (
        <div className="templates-grid">
          {templates.map((template: any) => (
            <div key={template.id} className="template-card">
              {/* Thumbnail */}
              <div className="template-thumbnail">
                {template.background_url ? (
                  <img
                    src={template.background_url}
                    alt={template.name}
                    className="template-image"
                  />
                ) : (
                  <div className="template-placeholder">
                    <span>لا توجد صورة</span>
                  </div>
                )}
              </div>

              {/* Template Info */}
              <div className="template-info">
                <h3 title={template.name}>{template.name}</h3>
                <p className="template-type">
                  {template.template_type === 'designed' ? '🎨 مصمم' : '⚡ سريع'}
                </p>
                {template.width_px && template.height_px && (
                  <p className="template-size">
                    {template.width_px} × {template.height_px} px
                  </p>
                )}
              </div>

              {/* Actions */}
              <div className="template-actions">
                <Can permission={PERM.TMPL_DESIGN}>
                  <button
                    className="action-btn edit-btn"
                    onClick={() => navigate(`/events/${eventId}/design?edit=${template.id}`)}
                    title="تحرير التصميم"
                  >
                    <Pencil size={16} />
                  </button>
                </Can>
                <button
                  className="action-btn preview-btn"
                  onClick={() => handlePreview(template)}
                  title="معاينة"
                  disabled={previewMutation.isPending}
                >
                  {previewMutation.isPending && selectedTemplate?.id === template.id ? (
                    <Loader2 size={16} className="spin" />
                  ) : (
                    <Eye size={16} />
                  )}
                </button>
                <Can permission={PERM.BATCH_DOWNLOAD}>
                  <button
                    className="action-btn download-btn"
                    onClick={handleDownloadPreview}
                    title="تحميل المعاينة"
                    disabled={!selectedTemplate || previewMutation.isPending}
                  >
                    <Download size={16} />
                  </button>
                </Can>
                <Can permission={PERM.TMPL_DELETE}>
                  <button
                    className="action-btn delete-btn"
                    onClick={() => handleDelete(template)}
                    title="حذف"
                    disabled={deleteMutation.isPending}
                  >
                    {deleteMutation.isPending ? (
                      <Loader2 size={16} className="spin" />
                    ) : (
                      <Trash2 size={16} />
                    )}
                  </button>
                </Can>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Preview Modal */}
      {showPreviewModal && (
        <div className="preview-modal-overlay" onClick={() => setShowPreviewModal(false)}>
          <div className="preview-modal" onClick={e => e.stopPropagation()}>
            <div className="preview-modal-header">
              <h2>معاينة القالب - {selectedTemplate?.name}</h2>
              <button
                className="close-btn"
                onClick={() => setShowPreviewModal(false)}
              >
                ✕
              </button>
            </div>

            <div className="preview-modal-content">
              {/* Preview Image */}
              <div className="preview-image-container">
                {previewMutation.data ? (
                  <img
                    src={previewMutation.data}
                    alt="معاينة"
                    className="preview-image"
                  />
                ) : (
                  <div className="preview-loading">
                    <Loader2 size={32} className="spin" />
                    <p>جاري تحضير المعاينة...</p>
                  </div>
                )}
              </div>

              {/* Preview Data Editor */}
              <div className="preview-data-editor">
                <h3>بيانات الاختبار</h3>
                <div className="preview-form">
                  {activePreviewFields.length === 0 ? (
                    <p style={{ opacity: 0.6, fontSize: 13, marginBottom: 15 }}>لا توجد حقول ديناميكية في هذا القالب.</p>
                  ) : (
                    activePreviewFields.map((field) => (
                      <div className="form-group" key={field.key}>
                        <label>{field.label}</label>
                        <input
                          type={field.type}
                          value={field.isCustomData ? (previewData.custom_data?.[field.customKey] ?? '') : (previewData[field.key] ?? '')}
                          onChange={(e) => {
                            if (field.isCustomData) {
                              setPreviewData((prev: any) => ({
                                ...prev,
                                custom_data: {
                                  ...prev.custom_data,
                                  [field.customKey]: e.target.value
                                }
                              }))
                            } else {
                              setPreviewData((prev: any) => ({
                                ...prev,
                                [field.key]: e.target.value
                              }))
                            }
                          }}
                        />
                      </div>
                    ))
                  )}

                  <button
                    className="btn btn-secondary"
                    onClick={() => {
                      if (!selectedTemplate) return
                      previewMutation.mutate({ templateId: selectedTemplate.id, data: previewData })
                    }}
                    disabled={previewMutation.isPending}
                  >
                    {previewMutation.isPending ? (
                      <>
                        <Loader2 size={14} className="spin" />
                        جاري التحديث...
                      </>
                    ) : (
                      'تحديث المعاينة'
                    )}
                  </button>
                </div>
              </div>
            </div>

            <div className="preview-modal-footer">
              <button
                className="btn btn-secondary"
                onClick={() => setShowPreviewModal(false)}
              >
                إغلاق
              </button>
              <Can permission={PERM.BATCH_DOWNLOAD}>
                <button
                  className="btn btn-primary"
                  onClick={handleDownloadPreview}
                >
                  <Download size={16} />
                  تحميل المعاينة
                </button>
              </Can>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
