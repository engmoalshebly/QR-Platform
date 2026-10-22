import { LimitErrorNotice } from '@components/LimitErrorNotice'
import { getApiErrorCode } from '@services/http/client'
import { useEffect } from 'react'
import { EventModel, EventStats } from '../types'
import { Printer, QrCode, Sparkles, Users, Plus, FileSpreadsheet } from 'lucide-react'
import './EventTemplatesTab.css'
import '../pages/events.css'

import {
  useInvitationState,
  useQuickMode,
  useDesignMode,
  useTemplatePreview,
  RsvpSection,
  LayoutSettings,
  QuickCountPanel,
  QuickNamesPanel,
  QuickExcelPanel,
  GenerateButton,
  TemplatePreviewModal,
  DesignModePanel,
  GenerationOperationsLog,
} from './invitations'
import { useGenerationCapabilities } from '../hooks/useGenerationOperations'
import { useServerImport } from '../hooks/useServerImport'
import { ServerImportPanel, ServerImportGenerate } from './invitations/ServerImportPanel'

interface Props {
  event: EventModel
  stats?: EventStats
}

export function EventInvitationsTab({ event, stats }: Props) {
  // ═══════════════════════════════════════════════════════════
  // Central state — all state, queries, and computed values
  // ═══════════════════════════════════════════════════════════
  const state = useInvitationState(event, stats)
  const { data: generationCaps } = useGenerationCapabilities()
  const serverImport = useServerImport(event.id, state.requireRsvp, 'quick')
  const designedImport = useServerImport(event.id, state.requireRsvp, 'designed')
  const {
    vipCount,
    setVipCount,
    normalCount,
    setNormalCount,
    guestPrefix,
    setGuestPrefix,
    generationSource,
    setGenerationSource,
    quickInputMode,
    setQuickInputMode,
    excelImportedGuests,
    excelImportFileName,
    excelImportErrors,
    quickManualGuests,
    quickFormName,
    setQuickFormName,
    quickFormCount,
    setQuickFormCount,
    quickFormClass,
    setQuickFormClass,
    quickDynamicFields,
    newQuickFieldName,
    setNewQuickFieldName,
    quickFormPhone,
    setQuickFormPhone,
    quickFormEmail,
    setQuickFormEmail,
    quickFormCustomFields,
    setQuickFormCustomFields,
    designTemplateId,
    designExcelFile,
    designExcelColumns,
    designColumnMapping,
    setDesignColumnMapping,
    dynamicFields,
    showSettings,
    setShowSettings,
    layout,
    updateLayout,
    localError,
    requireRsvp,
    setRequireRsvp,
    modalAlert,
    setModalAlert,
    singleGuestName,
    setSingleGuestName,
    singleGuestCount,
    setSingleGuestCount,
    singleGuestClass,
    setSingleGuestClass,
    showSingleGuestModal,
    setShowSingleGuestModal,
    selectedTemplateForPreview,
    showPreviewModal,
    setShowPreviewModal,
    activePreviewFields,
    previewData,
    setPreviewData,
    isPending,
    data,
    isError,
    error,
    remainingVip,
    remainingNormal,
    plannedVipCount,
    plannedNormalCount,
    isFormValid,
    barcodePerPage,
    totalInvitations,
    estimatedPages,
    isQuickRsvpMissingContact,
  } = state

  // ═══════════════════════════════════════════════════════════
  // Business logic hooks
  // ═══════════════════════════════════════════════════════════
  const quickMode = useQuickMode(state, event)
  const {
    addQuickManualGuest,
    deleteQuickManualGuest,
    handleAddQuickField,
    removeQuickDynamicField,
    addSingleGuest,
    handleGuestFileSelected,
    clearImportedGuests,
    downloadQuickExcelTemplate,
    handleGenerate,
  } = quickMode

  const designMode = useDesignMode(state, event)
  const {
    clearDesignExcel,
    downloadDesignExcelTemplate,
    fetchDynamicFields,
    findDesignMappingMatch,
    validateDesignMapping,
  } = designMode

  const templatePreview = useTemplatePreview(state, event)
  const {
    handleDownloadPreview,
    previewMutation,
  } = templatePreview

  // ── Download Excel template (delegates to quick or design) ──
  const downloadExcelTemplate = async () => {
    if (generationSource === 'design' && designTemplateId) {
      await downloadDesignExcelTemplate()
    } else {
      await downloadQuickExcelTemplate()
    }
  }

  // ── Clear imported guests ──
  const clearImportedGuestsForTarget = (target: 'excel' | 'design') => {
    if (target === 'excel') {
      clearImportedGuests()
    } else {
      clearDesignExcel()
    }
  }

  // ── Fetch dynamic fields when template changes ──
  useEffect(() => {
    fetchDynamicFields(designTemplateId)
  }, [designTemplateId, fetchDynamicFields])

  // ── Auto-map when template dynamic fields load ──
  useEffect(() => {
    if (designExcelColumns.length > 0 && designExcelFile && dynamicFields.length > 0) {
      const mapping = { ...designColumnMapping }
      let changed = false
      for (const field of dynamicFields) {
        if (!mapping[field.data_key]) {
          const match = findDesignMappingMatch(field.data_key, field.label, designExcelColumns)
          if (match) {
            mapping[field.data_key] = match
            changed = true
          }
        }
      }
      if (changed) {
        setDesignColumnMapping(mapping)
      }
      validateDesignMapping(mapping)
    }
  }, [
    designColumnMapping,
    designExcelColumns,
    designExcelFile,
    dynamicFields,
    findDesignMappingMatch,
    setDesignColumnMapping,
    validateDesignMapping,
  ])

  const totalImportedGuests = excelImportedGuests.length

  if (state.draftsLoading) return <p role="status">جارٍ استعادة إعدادات الإنشاء والمسودات…</p>
  if (state.draftRestoreFailed) return <div role="alert">{state.draftError}<button type="button" onClick={() => window.location.reload()}>إعادة تحميل المسودة</button></div>

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      <LimitErrorNotice error={getApiErrorCode(state.localErrorDetail) ? state.localErrorDetail : null} onRetry={generationSource === 'quick' ? handleGenerate : undefined} busy={isPending} />
      {(state.legacyQuickDraft || state.legacyDesignDraft) && <div className="gop" role="status">
        <p>توجد مسودة محلية سابقة لهذه المناسبة. يمكنك نقلها إلى مسودتك الخادمية إذا كانت القائمة الحالية فارغة. لن تُحذف إلا بعد نجاح النقل.</p>
        {state.legacyQuickDraft && <button type="button" className="inv-dl-btn" onClick={() => void state.restoreLegacyQuick()}>نقل مسودة الأسماء السريعة</button>}
        {state.legacyDesignDraft && <button type="button" className="inv-dl-btn" onClick={() => void state.restoreLegacyDesign()}>نقل مسودة الأسماء المصممة</button>}
      </div>}
      {/* ═══ GENERATION CARD ═══ */}
      <section className="inv-card">
        <div className="inv-card__header">
          <div className="inv-card__icon inv-card__icon--gold">
            <Printer size={20} />
          </div>
          <div>
            <h3 className="inv-card__title">إنشاء الدعوات للطباعة</h3>
            <p className="inv-card__desc">إنشاء ملفات PDF و ZIP للدعوات الجاهزة للطباعة</p>
          </div>
        </div>

        <div className="inv-card__body">
          <div className="inv-source-switch">
            <button
              type="button"
              className={`inv-source-switch__btn ${generationSource === 'quick' ? 'inv-source-switch__btn--active' : ''}`}
              onClick={() => setGenerationSource('quick')}
            >
              <QrCode size={15} /> دعوات برمز دخول فقط
            </button>
            <button
              type="button"
              className={`inv-source-switch__btn ${generationSource === 'design' ? 'inv-source-switch__btn--active' : ''}`}
              onClick={() => setGenerationSource('design')}
            >
              <Sparkles size={15} /> دعوات بتصميم مخصص
            </button>
          </div>

          {generationSource === 'quick' && (
            <div className="inv-design-inner-tabs" style={{ marginTop: 8, marginBottom: 16 }}>
              <button
                type="button"
                className={`inv-design-inner-tab ${quickInputMode === 'manual' ? 'inv-design-inner-tab--active' : ''}`}
                onClick={() => setQuickInputMode('manual')}
              >
                <Users size={14} /> تحديد عدد الدعوات
              </button>
              <button
                type="button"
                className={`inv-design-inner-tab ${quickInputMode === 'names' ? 'inv-design-inner-tab--active' : ''}`}
                onClick={() => setQuickInputMode('names')}
              >
                <Plus size={14} /> إضافة أسماء الضيوف
              </button>
              <button
                type="button"
                className={`inv-design-inner-tab ${quickInputMode === 'excel' ? 'inv-design-inner-tab--active' : ''}`}
                onClick={() => setQuickInputMode('excel')}
              >
                <FileSpreadsheet size={14} /> استيراد قائمة الضيوف
              </button>
            </div>
          )}

          {generationSource === 'quick' && quickInputMode === 'manual' && (
            <QuickCountPanel
              remainingVip={remainingVip}
              remainingNormal={remainingNormal}
              vipCount={vipCount}
              setVipCount={setVipCount}
              normalCount={normalCount}
              setNormalCount={setNormalCount}
              guestPrefix={guestPrefix}
              setGuestPrefix={setGuestPrefix}
              isPending={isPending}
            />
          )}

          {generationSource === 'quick' && quickInputMode === 'names' && (
            <QuickNamesPanel
              quickManualGuests={quickManualGuests}
              newQuickFieldName={newQuickFieldName}
              setNewQuickFieldName={setNewQuickFieldName}
              quickDynamicFields={quickDynamicFields}
              handleAddQuickField={handleAddQuickField}
              removeQuickDynamicField={removeQuickDynamicField}
              quickFormName={quickFormName}
              setQuickFormName={setQuickFormName}
              quickFormCount={quickFormCount}
              setQuickFormCount={setQuickFormCount}
              quickFormClass={quickFormClass}
              setQuickFormClass={setQuickFormClass}
              requireRsvp={requireRsvp}
              quickFormPhone={quickFormPhone}
              setQuickFormPhone={setQuickFormPhone}
              quickFormEmail={quickFormEmail}
              setQuickFormEmail={setQuickFormEmail}
              quickFormCustomFields={quickFormCustomFields}
              setQuickFormCustomFields={setQuickFormCustomFields}
              addQuickManualGuest={addQuickManualGuest}
              deleteQuickManualGuest={deleteQuickManualGuest}
            />
          )}

          {generationSource === 'quick' && quickInputMode === 'excel' && generationCaps?.enabled && (
            <ServerImportPanel importer={serverImport} requireRsvp={state.requireRsvp} />
          )}

          {generationSource === 'quick' && quickInputMode === 'excel' && !generationCaps?.enabled && (
            <QuickExcelPanel
              downloadExcelTemplate={downloadExcelTemplate}
              showSingleGuestModal={showSingleGuestModal}
              setShowSingleGuestModal={setShowSingleGuestModal}
              excelImportFileName={excelImportFileName}
              clearImportedGuests={clearImportedGuestsForTarget}
              excelImportErrors={excelImportErrors}
              excelImportedGuests={excelImportedGuests}
              totalImportedGuests={totalImportedGuests}
              plannedVipCount={plannedVipCount}
              plannedNormalCount={plannedNormalCount}
              totalInvitations={totalInvitations}
              handleGuestFileSelected={handleGuestFileSelected}
              singleGuestName={singleGuestName}
              setSingleGuestName={setSingleGuestName}
              singleGuestCount={singleGuestCount}
              setSingleGuestCount={setSingleGuestCount}
              singleGuestClass={singleGuestClass}
              setSingleGuestClass={setSingleGuestClass}
              addSingleGuest={addSingleGuest}
              localError={localError}
              isPending={isPending}
            />
          )}

          {generationSource !== 'design' && (
            <>
              {/* RSVP Toggle & Banner for Quick Mode */}
              {state.rsvpEnabled && quickInputMode !== 'manual' && <RsvpSection
                requireRsvp={requireRsvp}
                setRequireRsvp={setRequireRsvp}
                isMissingContact={isQuickRsvpMissingContact}
                missingContactCount={
                  quickInputMode === 'names'
                    ? quickManualGuests.length
                    : quickInputMode === 'excel'
                    ? excelImportedGuests.length
                    : vipCount + normalCount
                }
                missingContactSourceLabel={
                  quickInputMode === 'names'
                    ? 'حسب عدد الأسماء المدخلة يدوياً'
                    : quickInputMode === 'excel'
                    ? 'حسب عدد الأسطر في الملف الحالي'
                    : 'حسب عدد الدعوات المحدد'
                }
                style={{ marginBottom: '16px', marginTop: '16px' }}
              />}

              {/* Layout Settings for Quick Mode */}
              <LayoutSettings
                showSettings={showSettings}
                setShowSettings={setShowSettings}
                layout={layout}
                updateLayout={updateLayout}
                totalInvitations={totalInvitations}
                estimatedPages={estimatedPages}
                barcodePerPage={barcodePerPage}
              />

              {/* Entitlement failures belong next to the action that failed. */}
              {getApiErrorCode(state.localErrorDetail) && (
                <div>
                  <LimitErrorNotice error={state.localErrorDetail} onRetry={handleGenerate} busy={isPending} />
                  {requireRsvp && ['FEATURE_DISABLED', 'FEATURE_NOT_INCLUDED'].includes(getApiErrorCode(state.localErrorDetail) || '') && (
                    <button type="button" className="btn btn-ghost" style={{ marginTop: 8 }} onClick={() => {
                      setRequireRsvp(false)
                      state.setLocalError(null)
                    }}>استخدام دعوات مباشرة دون تأكيد حضور</button>
                  )}
                </div>
              )}

              {/* Generate Button & Result Display */}
              {generationSource === 'quick' && quickInputMode === 'excel' && generationCaps?.enabled ? (
                <ServerImportGenerate
                  importer={serverImport}
                  requireRsvp={state.requireRsvp}
                  layout={layout as unknown as Record<string, unknown>}
                  designedLayout={state.designedLayout as unknown as Record<string, unknown>}
                  templates={state.templates}
                  formats={state.canExport === false ? [] : ['pdf', 'zip']}
                  maxCards={generationCaps.max_cards}
                />
              ) : (
                <>
                  <GenerateButton
                    handleGenerate={handleGenerate}
                    isFormValid={isFormValid}
                    isPending={isPending}
                    totalInvitations={totalInvitations}
                    totalPeople={state.totalPeople}
                    canExport={state.canExport}
                    localError={localError}
                    isError={isError && !getApiErrorCode(error)}
                    error={error}
                    data={data}
                  />
                </>
              )}
            </>
          )}

          {generationSource === 'design' && (
            <DesignModePanel
              serverImport={generationCaps?.enabled ? designedImport : undefined}
              maxCards={generationCaps?.max_cards}
              state={state}
              designMode={designMode}
              templatePreview={templatePreview}
              event={event}
              downloadExcelTemplate={downloadExcelTemplate}
            />
          )}
        </div>
      </section>

      {generationCaps?.enabled && (
        <section className="inv-section" aria-labelledby="gen-ops-title">
          <h3 id="gen-ops-title">عمليات الإنشاء</h3>
          <GenerationOperationsLog eventId={event.id} />
        </section>
      )}

      {state.draftError && <div role="alert">{state.draftError}<button type="button" onClick={state.retryDraftSave}>إعادة محاولة الحفظ</button></div>}
      {state.draftsSaving && <p role="status">جارٍ حفظ المسودة… انتظر الحفظ قبل إغلاق الصفحة.</p>}
      {/* Preview Modal (Template Test-render) */}
      <TemplatePreviewModal
        showPreviewModal={showPreviewModal}
        setShowPreviewModal={setShowPreviewModal}
        selectedTemplateForPreview={selectedTemplateForPreview}
        previewMutation={previewMutation}
        activePreviewFields={activePreviewFields}
        previewData={previewData}
        setPreviewData={setPreviewData}
        handleDownloadPreview={handleDownloadPreview}
        modalAlert={modalAlert}
        setModalAlert={setModalAlert}
      />
    </div>
  )
}
