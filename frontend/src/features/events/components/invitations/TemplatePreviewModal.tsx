import React from 'react'
import { Loader2, Download } from 'lucide-react'

interface TemplatePreviewModalProps {
  showPreviewModal: boolean
  setShowPreviewModal: (val: boolean) => void
  selectedTemplateForPreview: any
  previewMutation: any
  activePreviewFields: any[]
  previewData: any
  setPreviewData: React.Dispatch<React.SetStateAction<any>>
  handleDownloadPreview: () => void
  modalAlert: { type: 'success' | 'error' | 'info'; title: string; message: string } | null
  setModalAlert: (val: any) => void
}

export function TemplatePreviewModal({
  showPreviewModal,
  setShowPreviewModal,
  selectedTemplateForPreview,
  previewMutation,
  activePreviewFields,
  previewData,
  setPreviewData,
  handleDownloadPreview,
  modalAlert,
  setModalAlert,
}: TemplatePreviewModalProps) {
  return (
    <>
      {showPreviewModal && (
        <div className="preview-modal-overlay" onClick={() => setShowPreviewModal(false)}>
          <div className="preview-modal" onClick={(e) => e.stopPropagation()}>
            <div className="preview-modal-header">
              <h2>معاينة القالب - {selectedTemplateForPreview?.name}</h2>
              <button
                type="button"
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
                  <img src={previewMutation.data} alt="معاينة" className="preview-image" />
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
                    <p style={{ opacity: 0.6, fontSize: 13, marginBottom: 15 }}>
                      لا توجد حقول ديناميكية في هذا القالب.
                    </p>
                  ) : (
                    activePreviewFields.map((field) => (
                      <div className="form-group" key={field.key}>
                        <label>{field.label}</label>
                        <input
                          type={field.type}
                          value={
                            field.isCustomData
                              ? previewData.custom_data?.[field.customKey] ?? ''
                              : previewData[field.key] ?? ''
                          }
                          onChange={(e) => {
                            if (field.isCustomData) {
                              setPreviewData((prev: any) => ({
                                ...prev,
                                custom_data: {
                                  ...prev.custom_data,
                                  [field.customKey]: e.target.value,
                                },
                              }))
                            } else {
                              setPreviewData((prev: any) => ({
                                ...prev,
                                [field.key]: e.target.value,
                              }))
                            }
                          }}
                        />
                      </div>
                    ))
                  )}

                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => {
                      const templateId = selectedTemplateForPreview?.id
                      if (!templateId) return
                      previewMutation.mutate({ templateId, data: previewData })
                    }}
                    disabled={previewMutation.isPending}
                  >
                    {previewMutation.isPending ? (
                      <>
                        <Loader2 size={14} className="spin" /> جاري التحديث...
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
                type="button"
                className="btn btn-secondary"
                onClick={() => setShowPreviewModal(false)}
              >
                إغلاق
              </button>
              <button type="button" className="btn btn-primary" onClick={handleDownloadPreview}>
                <Download size={16} /> تحميل المعاينة
              </button>
            </div>
          </div>
        </div>
      )}

      {modalAlert && (
        <div className="inv-quick-modal-overlay" role="dialog" aria-modal="true" style={{ zIndex: 11000 }}>
          <div className="inv-quick-modal" style={{ width: '400px', padding: '20px' }}>
            <div className="inv-quick-modal__header" style={{ marginBottom: '12px' }}>
              <div>
                <h3
                  style={{
                    fontSize: '18px',
                    fontWeight: 'bold',
                    color:
                      modalAlert.type === 'success'
                        ? '#10b981'
                        : modalAlert.type === 'error'
                        ? '#ef4444'
                        : '#3b82f6',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                  }}
                >
                  {modalAlert.type === 'success' ? '✓' : modalAlert.type === 'error' ? '⚠' : 'ℹ'}{' '}
                  {modalAlert.title}
                </h3>
              </div>
            </div>
            <div
              className="inv-quick-modal__body"
              style={{ fontSize: '13px', color: 'rgba(255, 255, 255, 0.7)', lineHeight: '1.6' }}
            >
              {modalAlert.message}
            </div>
            <div className="inv-quick-modal__actions" style={{ marginTop: '12px' }}>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => setModalAlert(null)}
                style={{
                  width: '100%',
                  justifyContent: 'center',
                  background:
                    modalAlert.type === 'success'
                      ? '#10b981'
                      : modalAlert.type === 'error'
                      ? '#ef4444'
                      : 'var(--color-primary)',
                  borderColor:
                    modalAlert.type === 'success'
                      ? '#10b981'
                      : modalAlert.type === 'error'
                      ? '#ef4444'
                      : 'var(--color-primary)',
                  color: '#fff',
                  padding: '10px',
                  fontWeight: '600',
                }}
              >
                موافق
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
