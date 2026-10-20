import { DownloadFileButton } from '@components/DownloadFileButton'
import { GenerationOperationTracker } from './GenerationOperationTracker'
import { useNavigate } from 'react-router-dom'
import {
  Loader2,
  CheckCircle2,
  Download,
  AlertCircle,
  QrCode,
  Plus,
  FileSpreadsheet,
  Sparkles,
  Users,
  Pencil,
  Eye,
  Trash2,
  Database,
  Info,
  Upload,
  X,
  Printer,
} from 'lucide-react'
import type { InvitationStateReturn } from './hooks/useInvitationState'
import type { useDesignMode } from './hooks/useDesignMode'
import type { useTemplatePreview } from './hooks/useTemplatePreview'
import { getCleanFieldLabel } from '../../utils/mappingUtils'
import { isPhoneField, isEmailField } from './types'
import { RsvpSection } from './RsvpSection'
import { Can, PERM } from '@shared/permissions'
import { readSpreadsheet } from '../../utils/spreadsheet'

interface DesignModePanelProps {
  state: InvitationStateReturn
  designMode: ReturnType<typeof useDesignMode>
  templatePreview: ReturnType<typeof useTemplatePreview>
  event: any
  downloadExcelTemplate: () => Promise<void>
}

export function DesignModePanel({
  state,
  designMode,
  templatePreview,
  event,
  downloadExcelTemplate,
}: DesignModePanelProps) {
  const navigate = useNavigate()

  const {
    isBatchRunning,
    isBatchReady,
    isBatchFailed,
    designStatus,
    designBatch,
    setDesignBatchId,
    setDesignStatus,
    designInputMode,
    setDesignInputMode,
    designTicketClass,
    setDesignTicketClass,
    isTemplatesLoading,
    matchingDesignedTemplates,
    designTemplateId,
    setDesignTemplateId,
    setDesignTemplateName,
    designCount,
    setDesignCount,
    designFormName,
    setDesignFormName,
    designFormCount,
    setDesignFormCount,
    requireRsvp,
    setRequireRsvp,
    designFormPhone,
    setDesignFormPhone,
    designFormEmail,
    setDesignFormEmail,
    dynamicFields,
    designFormCustomFields,
    setDesignFormCustomFields,
    designManualGuests,
    designExcelFile,
    designExcelRows,
    designExcelColumns,
    designColumnMapping,
    designMappingErrors,
    hoveredFieldKey,
    setHoveredFieldKey,
    selectedTemplate,
    designTemplateElements,
    designExcelReady,
    isGeneratingDesigned,
    isDesignRsvpMissingContact,
    setModalAlert,
  } = state

  const {
    addDesignManualGuest,
    deleteDesignManualGuest,
    handleDesignExcelUpload,
    handleDesignMappingChange,
    clearDesignExcel,
    handleGenerateDesignedFromExcel,
    handleGenerateDesigned,
  } = designMode

  const { handlePreview, handleDeleteTemplate, previewMutation, deleteMutation } = templatePreview

  return (
    <div className="inv-import-card inv-design-card" style={{ position: 'relative' }}>
      {state.designOperationId && (
        <div className="inv-design-overlay" role="dialog" aria-modal="true" aria-label="متابعة عملية التوليد">
          <div className="inv-design-overlay__card">
            <GenerationOperationTracker operationId={state.designOperationId} />
            <button type="button" className="inv-design-overlay__close-btn" onClick={() => state.setDesignOperationId('')}>
              إغلاق (العملية تستمر ويمكن متابعتها من «عمليات الإنشاء»)
            </button>
          </div>
        </div>
      )}

      {isBatchRunning && (
        <div className="inv-design-overlay">
          <div className="inv-design-overlay__card">
            <Loader2 size={44} className="inv-design-overlay__spin" />
            <h3 className="inv-design-overlay__title">جاري توليد الدعوات المصممة</h3>
            <p className="inv-design-overlay__desc">
              {designStatus || 'يرجى الانتظار حتى اكتمال التوليد...'}
            </p>

            {/* Progress Bar */}
            <div className="inv-design-progress">
              <div
                className="inv-design-progress__fill"
                style={{ width: `${designBatch?.progress || 0}%` }}
              />
            </div>
            <span className="inv-design-progress__pct">%{designBatch?.progress || 0}</span>

            {designBatch && (
              <span className="inv-design-progress__sub">
                تم معالجة {designBatch.count_done} من {designBatch.count_total} دعوة
              </span>
            )}
          </div>
        </div>
      )}

      {isBatchReady && (
        <div className="inv-design-overlay inv-design-overlay--success">
          <div className="inv-design-overlay__card">
            <div className="inv-design-overlay__icon inv-design-overlay__icon--success">
              <CheckCircle2 size={48} />
            </div>
            <h3 className="inv-design-overlay__title">تم التوليد بنجاح! 🎉</h3>
            <p className="inv-design-overlay__desc">
              تم توليد {designBatch?.count_total} دعوة مصممة بنجاح في{' '}
              {((designBatch?.duration_ms || 0) / 1000).toFixed(1)} ثانية.
            </p>

            <div className="inv-design-overlay__actions">
              {state.canExport && designBatch?.result_pdf_url && (
                <DownloadFileButton url={designBatch?.result_pdf_url} filename="invitations.pdf" className="inv-dl-btn inv-dl-btn--zip">
                  <Download size={14} /> PDF
                </DownloadFileButton>
              )}
              {state.canExport && designBatch?.result_zip_url && (
                <DownloadFileButton url={designBatch?.result_zip_url} filename="invitations.zip" className="inv-dl-btn inv-dl-btn--zip">
                  <Download size={14} /> ZIP
                </DownloadFileButton>
              )}
            </div>

            <button
              type="button"
              className="inv-design-overlay__close-btn"
              onClick={() => {
                setDesignBatchId('')
                setDesignStatus(null)
              }}
            >
              إغلاق النافذة
            </button>
          </div>
        </div>
      )}

      {isBatchFailed && (
        <div className="inv-design-overlay inv-design-overlay--error">
          <div className="inv-design-overlay__card">
            <div className="inv-design-overlay__icon inv-design-overlay__icon--error">
              <AlertCircle size={48} />
            </div>
            <h3 className="inv-design-overlay__title">فشلت عملية التوليد</h3>
            <p className="inv-design-overlay__desc">
              {designBatch?.error_message || 'حدث خطأ غير متوقع أثناء معالجة البطاقات.'}
            </p>

            <button
              type="button"
              className="inv-design-overlay__close-btn inv-design-overlay__close-btn--error"
              onClick={() => {
                setDesignBatchId('')
                setDesignStatus(null)
              }}
            >
              إغلاق ومحاولة أخرى
            </button>
          </div>
        </div>
      )}

      {/* Header */}
      <div className="inv-import-card__header">
        <div>
          <strong>تصميم مخصص للدعوات</strong>
          <span>اختر نوع الدعوة والقالب، ثم ولّد ملفات PDF/ZIP جاهزة للطباعة.</span>
        </div>
      </div>

      {/* Sub-tabs selector for Design tab */}
      <div className="inv-design-inner-tabs" style={{ marginTop: 8, marginBottom: 16 }}>
        <button
          type="button"
          className={`inv-design-inner-tab ${designInputMode === 'count' ? 'inv-design-inner-tab--active' : ''}`}
          onClick={() => setDesignInputMode('count')}
        >
          <QrCode size={14} /> توليد بالعدد (تلقائي)
        </button>
        <button
          type="button"
          className={`inv-design-inner-tab ${designInputMode === 'names' ? 'inv-design-inner-tab--active' : ''}`}
          onClick={() => setDesignInputMode('names')}
        >
          <Plus size={14} /> إدخال يدوي بالأسماء
        </button>
        <button
          type="button"
          className={`inv-design-inner-tab ${designInputMode === 'excel' ? 'inv-design-inner-tab--active' : ''}`}
          onClick={() => setDesignInputMode('excel')}
        >
          <FileSpreadsheet size={14} /> استيراد بيانات من ملف Excel
        </button>
      </div>

      <div className="inv-design-body">
        {/* Section ① — Invitation Type */}
        <div className="inv-design-section">
          <label className="inv-design-section__label">
            <span className="inv-design-section__num">①</span> نوع الدعوات
          </label>
          <div className="inv-design-type-cards">
            <button
              type="button"
              className={`inv-design-type-card ${
                designTicketClass === 'vip' ? 'inv-design-type-card--active inv-design-type-card--vip' : ''
              }`}
              onClick={() => setDesignTicketClass('vip')}
            >
              <div className="inv-design-type-card__icon inv-design-type-card__icon--vip">
                <Sparkles size={22} />
              </div>
              <div className="inv-design-type-card__info">
                <strong>VIP</strong>
                <span>دعوات فاخرة</span>
              </div>
              {designTicketClass === 'vip' && (
                <CheckCircle2 size={18} className="inv-design-type-card__check" />
              )}
            </button>
            <button
              type="button"
              className={`inv-design-type-card ${
                designTicketClass === 'normal' ? 'inv-design-type-card--active' : ''
              }`}
              onClick={() => setDesignTicketClass('normal')}
            >
              <div className="inv-design-type-card__icon">
                <Users size={22} />
              </div>
              <div className="inv-design-type-card__info">
                <strong>عادي</strong>
                <span>دعوات عادية</span>
              </div>
              {designTicketClass === 'normal' && (
                <CheckCircle2 size={18} className="inv-design-type-card__check" />
              )}
            </button>
          </div>
        </div>

        {/* Section ② — Template Selection */}
        <div className="inv-design-section">
          <label className="inv-design-section__label">
            <span className="inv-design-section__num">②</span> القالب (
            {designTicketClass === 'vip' ? 'VIP' : 'عادي'})
          </label>
          {isTemplatesLoading ? (
            <div className="inv-design-templates-grid">
              {[1, 2, 3].map((n) => (
                <div key={n} className="inv-design-template-skeleton">
                  <div className="inv-design-template-skeleton__thumb" />
                  <div className="inv-design-template-skeleton__name" />
                </div>
              ))}
            </div>
          ) : matchingDesignedTemplates.length === 0 ? (
            <div className="inv-design-empty-templates">
              <QrCode size={28} style={{ opacity: 0.3 }} />
              <p>لا توجد قوالب {designTicketClass === 'vip' ? 'VIP' : 'عادية'} بعد</p>
              <span>افتح محرر التصميم لإنشاء قالب جديد</span>
              <Can permission={PERM.TMPL_CREATE}>
                <button
                  type="button"
                  className="inv-design-editor-btn"
                  style={{ marginTop: 12 }}
                  onClick={() =>
                    navigate(
                      `/events/${event.id}/design?class=${designTicketClass}${
                        designInputMode === 'excel' ? '&mode=excel' : ''
                      }`
                    )
                  }
                >
                  <Plus size={14} /> إنشاء قالب جديد
                </button>
              </Can>
            </div>
          ) : (
            <div className="inv-design-templates-grid">
              {matchingDesignedTemplates.map(({ template: tpl, hasDynamic, dynamicCount }) => (
                <div
                  key={tpl.id}
                  className={`inv-design-template-card ${
                    designTemplateId === tpl.id ? 'inv-design-template-card--active' : ''
                  }`}
                  onClick={() => {
                    setDesignTemplateId(tpl.id)
                    setDesignTemplateName(tpl.name)
                  }}
                >
                  <div className="inv-design-template-card__thumb-container">
                    {tpl.background_url ? (
                      <img src={tpl.background_url} alt={tpl.name} className="inv-design-template-card__thumb" />
                    ) : (
                      <div className="inv-design-template-card__placeholder">
                        <QrCode size={24} style={{ opacity: 0.3 }} />
                      </div>
                    )}
                    <div className="inv-design-template-card__actions-overlay">
                      <Can permission={PERM.TMPL_EDIT}>
                        <button
                          type="button"
                          className="inv-card-action-btn inv-card-action-btn--edit"
                          onClick={(e) => {
                            e.stopPropagation()
                            navigate(
                              `/events/${event.id}/design?edit=${tpl.id}${
                                designInputMode === 'excel' ? '&mode=excel' : ''
                              }`
                            )
                          }}
                          title="تحرير التصميم"
                        >
                          <Pencil size={14} />
                        </button>
                      </Can>
                      <button
                        type="button"
                        className="inv-card-action-btn inv-card-action-btn--preview"
                        onClick={async (e) => {
                          e.stopPropagation()
                          await handlePreview(tpl)
                        }}
                        title="معاينة"
                        disabled={previewMutation.isPending}
                      >
                        {previewMutation.isPending && selectedTemplate?.id === tpl.id ? (
                          <Loader2 size={14} className="spin" />
                        ) : (
                          <Eye size={14} />
                        )}
                      </button>
                      <Can permission={PERM.TMPL_DELETE}>
                        <button
                          type="button"
                          className="inv-card-action-btn inv-card-action-btn--delete"
                          onClick={(e) => {
                            e.stopPropagation()
                            handleDeleteTemplate(tpl)
                          }}
                          title="حذف"
                          disabled={deleteMutation.isPending}
                        >
                          {deleteMutation.isPending && selectedTemplate?.id === tpl.id ? (
                            <Loader2 size={14} className="spin" />
                          ) : (
                            <Trash2 size={14} />
                          )}
                        </button>
                      </Can>
                    </div>
                  </div>
                  <div className="inv-design-template-card__name">{tpl.name}</div>
                  <div
                    className={`inv-design-template-card__type ${
                      hasDynamic ? 'inv-design-template-card__type--dynamic' : ''
                    }`}
                  >
                    {hasDynamic ? (
                      <>
                        <Database size={10} /> {dynamicCount} حقل
                      </>
                    ) : (
                      <>
                        <QrCode size={10} /> QR
                      </>
                    )}
                  </div>
                  {designTemplateId === tpl.id && (
                    <div className="inv-design-template-card__badge">
                      <CheckCircle2 size={14} />
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Section ③ — Data Source */}
        <div className="inv-design-section">
          <label className="inv-design-section__label">
            <span className="inv-design-section__num">③</span>{' '}
            {designInputMode === 'count'
              ? 'تحديد عدد الدعوات'
              : designInputMode === 'names'
              ? 'إدخال بيانات الضيوف يدوياً'
              : 'تحميل بيانات الضيوف من Excel'}
          </label>

          {designInputMode === 'count' ? (
            <div className="inv-design-count-panel">
              <div className="inv-design-tab-row">
                <div style={{ flex: 1 }}>
                  <label className="inv-label">عدد الدعوات</label>
                  <input
                    type="number"
                    min={1}
                    max={1000}
                    value={designCount}
                    onChange={(e) => setDesignCount(Number(e.target.value))}
                    className="inv-input"
                    style={{ width: '100%' }}
                    disabled={isGeneratingDesigned}
                  />
                </div>
                <button
                  type="button"
                  className="inv-design-editor-btn"
                  onClick={() => navigate(`/events/${event.id}/design?mode=count`)}
                >
                  <Sparkles size={14} /> فتح محرر التصميم
                </button>
              </div>
            </div>
          ) : designInputMode === 'names' ? (
            <div className="inv-design-excel-panel" style={{ padding: 20 }}>
              {!designTemplateId ? (
                <div className="inv-design-excel-notice">
                  <AlertCircle size={18} />
                  <span>يرجى اختيار قالب من الأعلى أولاً للبدء في إدخال أسماء وبيانات الضيوف المخصصة.</span>
                </div>
              ) : (
                <>
                  <div className="inv-design-excel-header" style={{ marginBottom: 12 }}>
                    <div>
                      <strong>إدخال بيانات الضيوف يدوياً</strong>
                      <span>أدخل أسماء الضيوف وملأ بيانات التصميم مباشرة لتوليد كروتهم المخصصة.</span>
                    </div>
                  </div>

                  {/* Form to add a guest with dynamic fields */}
                  <div
                    className="inv-design-tab-row inv-guest-entry"
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 16,
                      background: 'var(--color-bg-card)',
                      padding: 18,
                      borderRadius: 12,
                      marginBottom: 16,
                    }}
                  >
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, width: '100%' }}>
                      <div style={{ flex: '2 1 250px' }}>
                        <label className="inv-label">
                          اسم الضيف <span style={{ color: '#ef4444' }}>*</span>
                        </label>
                        <input
                          type="text"
                          value={designFormName}
                          onChange={(e) => setDesignFormName(e.target.value)}
                          className="inv-input"
                          style={{ width: '100%' }}
                          placeholder="اكتب اسم الضيف الكامل..."
                        />
                      </div>
                      <div style={{ flex: '1 1 100px' }}>
                        <label className="inv-label">عدد الدعوات</label>
                        <input
                          type="number"
                          min={1}
                          value={designFormCount}
                          onChange={(e) => setDesignFormCount(Number(e.target.value))}
                          className="inv-input"
                          style={{ width: '100%' }}
                        />
                      </div>
                    </div>

                    {requireRsvp && (
                      <div
                        style={{
                          display: 'flex',
                          flexWrap: 'wrap',
                          gap: 12,
                          width: '100%',
                          borderTop: '1px solid var(--color-border)',
                          paddingTop: 12,
                        }}
                      >
                        <div style={{ flex: '1 1 200px' }}>
                          <label className="inv-label">
                            رقم الجوال
                          </label>
                          <input
                            type="text"
                            value={designFormPhone}
                            onChange={(e) => setDesignFormPhone(e.target.value)}
                            className="inv-input"
                            style={{ width: '100%' }}
                            placeholder="رقم دولي، مثال: +967700000000"
                          />
                        </div>
                        <div style={{ flex: '1 1 200px' }}>
                          <label className="inv-label">
                            البريد الإلكتروني
                          </label>
                          <input
                            type="text"
                            value={designFormEmail}
                            onChange={(e) => setDesignFormEmail(e.target.value)}
                            className="inv-input"
                            style={{ width: '100%' }}
                            placeholder="مثال: guest@example.com"
                          />
                        </div>
                      </div>
                    )}

                    {/* Render custom dynamic fields */}
                    {dynamicFields.filter((f) => {
                      if (f.data_key === 'guest.name') return false
                      if (
                        requireRsvp &&
                        (isPhoneField(f.data_key) ||
                          isPhoneField(f.label) ||
                          isEmailField(f.data_key) ||
                          isEmailField(f.label))
                      )
                        return false
                      return true
                    }).length > 0 && (
                      <div
                        style={{
                          display: 'flex',
                          flexWrap: 'wrap',
                          gap: 12,
                          width: '100%',
                          borderTop: '1px solid var(--color-border)',
                          paddingTop: 12,
                        }}
                      >
                        {dynamicFields.map((field) => {
                          if (field.data_key === 'guest.name') return null
                          if (
                            requireRsvp &&
                            (isPhoneField(field.data_key) ||
                              isPhoneField(field.label) ||
                              isEmailField(field.data_key) ||
                              isEmailField(field.label))
                          )
                            return null
                          return (
                            <div key={field.data_key} style={{ flex: '1 1 200px' }}>
                              <label className="inv-label">{field.label}</label>
                              <input
                                type="text"
                                className="inv-input"
                                style={{ width: '100%' }}
                                value={designFormCustomFields[field.data_key] || ''}
                                onChange={(e) =>
                                  setDesignFormCustomFields((prev) => ({
                                    ...prev,
                                    [field.data_key]: e.target.value,
                                  }))
                                }
                                placeholder={`بيانات ${field.label}...`}
                              />
                            </div>
                          )
                        })}
                      </div>
                    )}

                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'flex-end',
                        width: '100%',
                        borderTop: '1px solid var(--color-border)',
                        paddingTop: 12,
                      }}
                    >
                      <Can permission={PERM.GUEST_CREATE}>
                        <button
                          type="button"
                          className="btn btn-primary"
                          onClick={addDesignManualGuest}
                          style={{
                            height: '42px',
                            background: 'var(--color-primary)',
                            borderColor: 'var(--color-primary)',
                            color: '#fff',
                            padding: '0 24px',
                            borderRadius: '8px',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '6px',
                            fontWeight: '600',
                          }}
                        >
                          <Plus size={16} /> إضافة الضيف للقائمة
                        </button>
                      </Can>
                    </div>
                  </div>

                  {/* Preview List Table */}
                  {designManualGuests.length > 0 ? (
                    <div className="inv-design-preview" style={{ marginTop: 12 }}>
                      <div className="inv-design-preview__header">
                        <strong>قائمة الضيوف الحالية ({designManualGuests.length} ضيوف)</strong>
                      </div>
                      <div className="inv-design-preview__table-wrap">
                        <table className="inv-design-preview__table">
                          <thead>
                            <tr>
                              <th>#</th>
                              <th>اسم الضيف</th>
                              <th>عدد الأشخاص</th>
                              {requireRsvp && (
                                <>
                                  <th>رقم الجوال</th>
                                  <th>البريد الإلكتروني</th>
                                </>
                              )}
                              {dynamicFields.map((f) => {
                                if (f.data_key === 'guest.name') return null
                                if (
                                  requireRsvp &&
                                  (isPhoneField(f.data_key) ||
                                    isPhoneField(f.label) ||
                                    isEmailField(f.data_key) ||
                                    isEmailField(f.label))
                                )
                                  return null
                                return <th key={f.data_key}>{f.label}</th>
                              })}
                              <th style={{ width: 100 }}>إجراءات</th>
                            </tr>
                          </thead>
                          <tbody>
                            {designManualGuests.map((guest, index) => (
                              <tr key={index}>
                                <td>{index + 1}</td>
                                <td>{guest.guest_name}</td>
                                <td>{guest.invitation_count}</td>
                                {requireRsvp && (
                                  <>
                                    <td>
                                      {guest.custom_fields?.[
                                        dynamicFields.find((f) => isPhoneField(f.data_key) || isPhoneField(f.label))
                                          ?.data_key || ''
                                      ] ||
                                        guest.custom_fields?.['رقم الجوال'] ||
                                        guest.custom_fields?.['جوال'] ||
                                        '—'}
                                    </td>
                                    <td>
                                      {guest.custom_fields?.[
                                        dynamicFields.find((f) => isEmailField(f.data_key) || isEmailField(f.label))
                                          ?.data_key || ''
                                      ] ||
                                        guest.custom_fields?.['البريد الإلكتروني'] ||
                                        guest.custom_fields?.['بريد'] ||
                                        '—'}
                                    </td>
                                  </>
                                )}
                                {dynamicFields.map((f) => {
                                  if (f.data_key === 'guest.name') return null
                                  if (
                                    requireRsvp &&
                                    (isPhoneField(f.data_key) ||
                                      isPhoneField(f.label) ||
                                      isEmailField(f.data_key) ||
                                      isEmailField(f.label))
                                  )
                                    return null
                                  return <td key={f.data_key}>{guest.custom_fields?.[f.data_key] || '—'}</td>
                                })}
                                <td>
                                  <Can permission={PERM.GUEST_DELETE}>
                                    <button
                                      type="button"
                                      className="inv-card-action-btn inv-card-action-btn--delete"
                                      onClick={() => deleteDesignManualGuest(index)}
                                      style={{
                                        position: 'relative',
                                        border: '1px solid rgba(239, 68, 68, 0.3)',
                                        background: 'rgba(239, 68, 68, 0.08)',
                                        color: '#ef4444',
                                      }}
                                      title="حذف"
                                    >
                                      <Trash2 size={13} />
                                    </button>
                                  </Can>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  ) : (
                    <div
                      style={{
                        textAlign: 'center',
                        padding: '30px 20px',
                        border: '1px dashed var(--color-border)',
                        borderRadius: 12,
                        opacity: 0.6,
                        fontSize: '13px',
                      }}
                    >
                      القائمة فارغة حالياً. ابدأ بإدخال بيانات ضيف وإضافته للقائمة أعلاه.
                    </div>
                  )}
                </>
              )}
            </div>
          ) : (
            <div className="inv-design-excel-panel">
              {!designTemplateId ? (
                <div
                  className="inv-design-flow2-container"
                  style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}
                >
                  <div className="inv-design-excel-notice">
                    <AlertCircle size={18} />
                    <span>
                      يرجى اختيار قالب من الأعلى، أو البدء برفع ملف الـ Excel الخاص بك أولاً لتصميم قالب
                      متناسق معه مباشرة.
                    </span>
                  </div>

                  <div className="inv-design-excel-upload" style={{ marginTop: '4px' }}>
                    <label
                      className={`inv-design-excel-dropzone ${
                        designExcelFile ? 'inv-design-excel-dropzone--done' : ''
                      }`}
                    >
                      <input
                        type="file"
                        accept=".xlsx,.csv"
                        onClick={(e) => {
                          e.currentTarget.value = ''
                        }}
                        onChange={async (e) => {
                          const file = e.target.files?.[0]
                          if (!file) return
                          try {
                            const rows = await readSpreadsheet(file)
                            if (rows.length > 0) {
                              const columnNames = Object.keys(rows[0])
                              // Save columns in sessionStorage for the designer
                              sessionStorage.setItem(`excel_cols_${event.id}`, JSON.stringify(columnNames))
                              sessionStorage.setItem(`excel_name_${event.id}`, file.name)

                              await handleDesignExcelUpload(file)
                              setModalAlert({
                                title: 'تم قراءة الملف بنجاح',
                                message: `تم قراءة ${columnNames.length} أعمدة بنجاح من الملف. يمكنك الآن الانتقال لتصميم القالب مباشرة.`,
                                type: 'success',
                              })
                            } else {
                              setModalAlert({
                                title: 'ملف فارغ',
                                message: 'ملف Excel فارغ أو لا يحتوي على صفوف بيانات',
                                type: 'error',
                              })
                            }
                          } catch (err: any) {
                            setModalAlert({
                              title: 'خطأ في قراءة الملف',
                              message: `خطأ في قراءة ملف الإكسل: ${err.message}`,
                              type: 'error',
                            })
                          }
                        }}
                        hidden
                      />
                      {designExcelFile ? (
                        <>
                          <CheckCircle2 size={28} style={{ color: '#10b981' }} />
                          <span className="inv-design-excel-dropzone__name">{designExcelFile.name}</span>
                          <span className="inv-design-excel-dropzone__hint">
                            {designExcelRows.length} ضيف · انقر لتغيير الملف
                          </span>
                        </>
                      ) : (
                        <>
                          <Upload size={28} />
                          <span className="inv-design-excel-dropzone__name">رفع ملف Excel أولاً لبدء التصميم</span>
                          <span className="inv-design-excel-dropzone__hint">
                            ملفات Excel (.xlsx) أو CSV (.csv) لربط أعمدتها بالتصميم مباشرة
                          </span>
                        </>
                      )}
                    </label>
                    {designExcelFile && (
                      <button type="button" className="inv-design-excel-clear" onClick={clearDesignExcel}>
                        <X size={14} /> مسح الملف
                      </button>
                    )}
                  </div>

                  {designExcelFile && (
                    <div style={{ display: 'flex', justifyContent: 'center', marginTop: '4px' }}>
                      <button
                        type="button"
                        className="btn btn-primary"
                        onClick={() => {
                          navigate(`/events/${event.id}/design?class=${designTicketClass}&mode=excel`)
                        }}
                        style={{
                          background: 'var(--color-primary)',
                          borderColor: 'var(--color-primary)',
                          padding: '10px 20px',
                          fontSize: '14px',
                          fontWeight: '600',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '8px',
                          borderRadius: '8px',
                        }}
                      >
                        <Sparkles size={16} />
                        البدء بتصميم قالب جديد باستخدام أعمدة هذا الملف
                      </button>
                    </div>
                  )}
                </div>
              ) : (
                <>
                  <div className="inv-design-excel-header">
                    <div>
                      <strong>رفع بيانات الضيوف</strong>
                      <span>ملف Excel (.xlsx) يحتوي على أسماء الضيوف وبيانات التصميم</span>
                    </div>
                    <button type="button" className="inv-dl-btn inv-dl-btn--zip" onClick={() => { void downloadExcelTemplate() }}>
                      <Download size={15} /> تنزيل نموذج القالب
                    </button>
                  </div>

                  <ol className="inv-import-steps" aria-label="خطوات استيراد بيانات القالب">
                    <li><strong>1. نزّل النموذج</strong><span>املأ ورقة «المدعوين». كل صف يمثل دعوة، وعدد الأشخاص يحدد سعتها.</span></li>
                    <li><strong>2. ارفع الملف واربط الحقول</strong><span>راجع الربط التلقائي واختر العمود المناسب لكل حقل مطلوب.</span></li>
                    <li><strong>3. راجع ثم ولّد</strong><span>تحقق من القيم والأعداد والفئة قبل إنشاء ملفات PDF وZIP.</span></li>
                  </ol>

                  {dynamicFields.length > 1 && (
                    <div className="inv-design-fields-hint">
                      <span className="inv-design-fields-hint__title">📋 حقول التصميم المكتشفة:</span>
                      <div className="inv-design-fields-hint__list">
                        {dynamicFields.map((f) => (
                          <span
                            key={f.data_key}
                            className={`inv-design-fields-hint__tag ${
                              f.required ? 'inv-design-fields-hint__tag--req' : ''
                            }`}
                          >
                            {f.label} {f.required && '*'}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {designExcelFile && designExcelColumns.length > 0 && (
                    <div className="inv-design-mapping-container-wrapper">
                      <div className="inv-design-mapping__header" style={{ marginBottom: 12 }}>
                        <strong>ربط أعمدة الملف بحقول الدعوة</strong>
                        <span>
                          تم الكشف التلقائي عن{' '}
                          {Object.keys(designColumnMapping).filter((k) => designColumnMapping[k]).length}/
                          {dynamicFields.length} حقل
                        </span>
                      </div>
                      {dynamicFields.length === 0 ? (
                        <div
                          className="inv-design-excel-notice"
                          style={{
                            marginBottom: 12,
                            background: 'rgba(59, 130, 246, 0.08)',
                            color: '#60a5fa',
                            borderColor: 'rgba(59, 130, 246, 0.18)',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '8px',
                            padding: '10px 14px',
                            borderRadius: '8px',
                          }}
                        >
                          <Info size={16} />
                          <span>
                            هذا القالب يحتوي على باركود وعناصر ثابتة فقط (لا يحتوي على نصوص ديناميكية). سيتم
                            توليد البطاقات بالخلفية والباركود مباشرة لكل صف في ملف Excel.
                          </span>
                        </div>
                      ) : (
                        designMappingErrors.length > 0 && (
                          <div className="inv-design-mapping__errors" style={{ marginBottom: 12 }}>
                            {designMappingErrors.map((err, i) => (
                              <div key={i} className="inv-design-mapping__error-item">
                                <AlertCircle size={14} /> {err}
                              </div>
                            ))}
                          </div>
                        )
                      )}

                      <div className="inv-design-mapping-split">
                        {/* Mapping Fields */}
                        <div className="inv-design-mapping-form">
                          <div className="inv-design-mapping__grid-vertical">
                            {dynamicFields.map((field) => {
                              const isHovered = hoveredFieldKey === field.data_key
                              const mappedCol = designColumnMapping[field.data_key]
                              const sampleVal = mappedCol ? designExcelRows[0]?.[mappedCol] : null

                              return (
                                <div
                                  key={field.data_key}
                                  className={`inv-design-mapping-card ${
                                    isHovered ? 'inv-design-mapping-card--hovered' : ''
                                  } ${mappedCol ? 'inv-design-mapping-card--mapped' : ''} ${
                                    field.required && !mappedCol
                                      ? 'inv-design-mapping-card--required-error'
                                      : ''
                                  }`}
                                  onMouseEnter={() => setHoveredFieldKey(field.data_key)}
                                  onMouseLeave={() => setHoveredFieldKey(null)}
                                >
                                  <div className="inv-design-mapping-card-header">
                                    <label className="inv-design-mapping-card-label">
                                      {field.label}
                                      {field.required && (
                                        <span className="inv-design-badge inv-design-badge--required">
                                          إلزامي للكرت
                                        </span>
                                      )}
                                      {!field.required && (
                                        <span className="inv-design-badge inv-design-badge--optional">
                                          اختياري
                                        </span>
                                      )}
                                    </label>
                                    {mappedCol && <CheckCircle2 size={14} style={{ color: '#10b981' }} />}
                                  </div>
                                  <span className="inv-design-mapping-card-key">
                                    مفتاح الحقل: {field.data_key}
                                  </span>

                                  <select
                                    value={mappedCol || ''}
                                    onChange={(e) => handleDesignMappingChange(field.data_key, e.target.value)}
                                    className="inv-input inv-design-mapping-select"
                                  >
                                    <option value="">— اختر عمود —</option>
                                    {designExcelColumns.map((col) => (
                                      <option key={col.name} value={col.name}>
                                        {col.name}{' '}
                                        {col.sampleValues[0] ? `(${col.sampleValues[0]})` : ''}
                                      </option>
                                    ))}
                                  </select>

                                  {sampleVal && (
                                    <div className="inv-design-mapping-card-preview">
                                      <span className="preview-label">القيمة الأولى للمعاينة:</span>
                                      <span className="preview-val">{sampleVal}</span>
                                    </div>
                                  )}
                                </div>
                              )
                            })}
                          </div>
                        </div>

                        {/* Live Card Preview */}
                        <div className="inv-design-card-preview-panel">
                          <div className="preview-panel-title">معاينة كرت الدعوة التفاعلية</div>
                          <div className="preview-panel-subtitle">
                            مرر الماوس فوق أي حقل لرؤية موقعه على التصميم
                          </div>

                          {selectedTemplate && (
                            <div
                              className="card-preview-container"
                              style={{
                                aspectRatio:
                                  selectedTemplate.orientation === 'landscape' ||
                                  (selectedTemplate.width_px || 1080) > (selectedTemplate.height_px || 1920)
                                    ? '1.414 / 1'
                                    : '1 / 1.414',
                                backgroundColor: selectedTemplate.background_color || '#111827',
                                backgroundImage: selectedTemplate.background_url
                                  ? `url(${selectedTemplate.background_url})`
                                  : 'none',
                              }}
                            >
                              {/* Render design overlay elements */}
                              {designTemplateElements
                                .filter((el) => el.is_visible !== false)
                                .map((el) => {
                                  const isDynamic =
                                    el.element_type === 'guest_name' ||
                                    el.element_type === 'dynamic_text' ||
                                    [
                                      'event_date',
                                      'event_time',
                                      'event_location',
                                      'seat_number',
                                      'gate',
                                      'hall',
                                      'table_number',
                                    ].includes(el.element_type)

                                  const key =
                                    el.data_key ||
                                    (el.element_type === 'guest_name'
                                      ? 'guest.name'
                                      : `custom.${el.element_type}`)
                                  const mappedCol = designColumnMapping[key]

                                  let displayText = ''
                                  if (el.element_type === 'qr_code' || el.element_type === 'barcode') {
                                    displayText = el.element_type === 'qr_code' ? 'QR Code' : 'Barcode'
                                  } else if (isDynamic) {
                                    if (mappedCol) {
                                      displayText = designExcelRows[0]?.[mappedCol] || el.label || key
                                    } else {
                                      displayText = `{${getCleanFieldLabel(key, el.element_type, el.label)}}`
                                    }
                                  } else {
                                    displayText = el.static_content || el.label || ''
                                  }

                                  const isActive = hoveredFieldKey === key

                                  return (
                                    <div
                                      key={el.id}
                                      className={`card-preview-element ${
                                        isDynamic ? 'card-preview-element--dynamic' : ''
                                      } ${mappedCol ? 'card-preview-element--mapped' : ''} ${
                                        isActive ? 'card-preview-element--active' : ''
                                      } ${
                                        el.element_type === 'qr_code' || el.element_type === 'barcode'
                                          ? 'card-preview-element--qr'
                                          : ''
                                      }`}
                                      style={{
                                        left: `${el.x * 100}%`,
                                        top: `${el.y * 100}%`,
                                        width: `${el.width * 100}%`,
                                        height: `${el.height * 100}%`,
                                        transform: `rotate(${el.rotation || 0}deg)`,
                                        fontFamily: el.font_family || 'Cairo',
                                        fontSize: `${Math.max(7, (el.font_size || 14) * 0.16)}px`,
                                        color: el.font_color || '#ffffff',
                                        fontWeight: el.font_weight || 'normal',
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent:
                                          el.text_align === 'left'
                                            ? 'flex-start'
                                            : el.text_align === 'right'
                                            ? 'flex-end'
                                            : 'center',
                                        textAlign: (el.text_align as any) || 'center',
                                        pointerEvents: isDynamic ? 'auto' : 'none',
                                      }}
                                      onMouseEnter={() => isDynamic && setHoveredFieldKey(key)}
                                      onMouseLeave={() => isDynamic && setHoveredFieldKey(null)}
                                    >
                                      {el.element_type === 'qr_code' && (
                                        <div className="preview-qr-box">
                                          <span>QR</span>
                                        </div>
                                      )}
                                      {el.element_type === 'barcode' && (
                                        <div className="preview-barcode-box">
                                          <span>||||</span>
                                        </div>
                                      )}
                                      {el.element_type !== 'qr_code' && el.element_type !== 'barcode' && (
                                        <span className="truncate-text">{displayText}</span>
                                      )}
                                    </div>
                                  )
                                })}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  )}

                  <div className="inv-design-excel-upload">
                    <label
                      className={`inv-design-excel-dropzone ${
                        designExcelFile ? 'inv-design-excel-dropzone--done' : ''
                      }`}
                    >
                      <input
                        type="file"
                        accept=".xlsx,.csv"
                        onClick={(e) => {
                          e.currentTarget.value = ''
                        }}
                        onChange={(e) => handleDesignExcelUpload(e.target.files?.[0] ?? null)}
                        hidden
                      />
                      {designExcelFile ? (
                        <>
                          <CheckCircle2 size={28} />
                          <span className="inv-design-excel-dropzone__name">{designExcelFile.name}</span>
                          <span className="inv-design-excel-dropzone__hint">
                            {designExcelRows.length} ضيف · انقر لتغيير الملف
                          </span>
                        </>
                      ) : (
                        <>
                          <Upload size={28} />
                          <span className="inv-design-excel-dropzone__name">اسحب الملف هنا أو انقر للاختيار</span>
                          <span className="inv-design-excel-dropzone__hint">ملفات Excel (.xlsx) أو CSV (.csv)</span>
                        </>
                      )}
                    </label>
                    {designExcelFile && (
                      <button type="button" className="inv-design-excel-clear" onClick={clearDesignExcel}>
                        <X size={14} /> مسح الملف
                      </button>
                    )}
                  </div>

                  {designExcelRows.length > 0 && (
                    <div className="inv-design-preview">
                      <div className="inv-design-preview__header">
                        <strong>مراجعة البيانات قبل التوليد</strong>
                        <span>{designExcelRows.length} ضيف</span>
                      </div>
                      <div className="inv-design-preview__table-wrap">
                        <table className="inv-design-preview__table">
                          <thead>
                            <tr>
                              <th>#</th>
                              {dynamicFields.length ? dynamicFields.map((f) => (
                                <th key={f.data_key}>{f.label}</th>
                              )) : designExcelColumns.map(col => <th key={col.name}>{col.name}</th>)}
                            </tr>
                          </thead>
                          <tbody>
                            {designExcelRows.slice(0, 5).map((row, i) => (
                              <tr key={i}>
                                <td style={{ opacity: 0.5, fontFamily: 'var(--font-en)' }}>{i + 1}</td>
                                {dynamicFields.map((f) => {
                                  const colName = designColumnMapping[f.data_key]
                                  return <td key={f.data_key}>{colName ? (row[colName] || 'فارغ') : 'غير مرتبط'}</td>
                                })}
                                {dynamicFields.length === 0 && designExcelColumns.map(col => <td key={col.name}>{row[col.name] || 'فارغ'}</td>)}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        {designExcelRows.length > 5 && (
                          <div className="inv-design-preview__more">
                            ... و {designExcelRows.length - 5} ضيف آخر
                          </div>
                        )}
                      </div>
                      <div className={`inv-design-preview__success ${!designExcelReady ? 'inv-design-preview__warning' : ''}`}>
                        {designExcelReady ? <><CheckCircle2 size={16} /> اكتمل التحقق من الحقول المطلوبة. راجع المعاينة قبل التوليد.</> : <><AlertCircle size={16} /> أكمل ربط الحقول المطلوبة والخلايا الفارغة قبل التوليد.</>}
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {/* RSVP Toggle for Design Mode */}
      {state.rsvpEnabled && designInputMode !== 'count' && <RsvpSection
        requireRsvp={requireRsvp}
        setRequireRsvp={setRequireRsvp}
        isMissingContact={isDesignRsvpMissingContact}
        missingContactCount={
          designInputMode === 'names'
            ? designManualGuests.length
            : designInputMode === 'excel'
            ? designExcelRows.length
            : designCount
        }
        missingContactSourceLabel={
          designInputMode === 'names'
            ? 'حسب عدد الأسماء المدخلة يدوياً'
            : designInputMode === 'excel'
            ? 'حسب عدد الأسطر في الملف الحالي'
            : 'حسب عدد الدعوات المحدد'
        }
        style={{ marginTop: '20px', marginBottom: '8px' }}
      />}

      <p className="inv-hint">الحد الحالي 1000 دعوة للعملية الواحدة؛ كل دعوة قد تسمح بدخول عدة أشخاص.</p>
      {/* Generate Buttons */}
      <Can permission={PERM.INV_GENERATE}>
        {designInputMode === 'count' ? (
          <button
            type="button"
            className="inv-generate-btn"
            onClick={handleGenerateDesigned}
            disabled={isGeneratingDesigned || !designTemplateId || !Number.isInteger(designCount) || designCount < 1 || designCount > 1000}
            style={{ marginTop: 12 }}
          >
            <Printer size={18} />{' '}
            {isGeneratingDesigned ? 'جاري التوليد...' : `بدء التوليد (${designCount} دعوة)`}
          </button>
        ) : designInputMode === 'names' ? (
          designTemplateId &&
          designManualGuests.length > 0 && (
            <button
              type="button"
              className="inv-generate-btn"
              onClick={handleGenerateDesigned}
              disabled={isGeneratingDesigned || designManualGuests.length > 1000}
              style={{ marginTop: 12 }}
            >
              <Printer size={18} />{' '}
              {isGeneratingDesigned ? 'جاري التوليد...' : `بدء التوليد (${designManualGuests.length} دعوة)`}
            </button>
          )
        ) : (
          designTemplateId &&
          designExcelReady &&
          designExcelRows.length > 0 && (
            <button
              type="button"
              className="inv-generate-btn"
              onClick={handleGenerateDesignedFromExcel}
              disabled={isGeneratingDesigned || designExcelRows.length > 1000}
              style={{ marginTop: 12 }}
            >
              <Printer size={18} />{' '}
              {isGeneratingDesigned ? 'جاري التوليد...' : `بدء التوليد (${designExcelRows.length} دعوة)`}
            </button>
          )
        )}
      </Can>
    </div>
  )
}
