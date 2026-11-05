import { LimitErrorNotice } from '@components/LimitErrorNotice'
import { getApiErrorCode } from '@services/http/client'
import { useEffect, useState } from 'react'
import { EventModel, EventStats } from '../types'
import { Check, ChevronLeft, ChevronRight, Info, Printer, QrCode, Sparkles, Users, Plus, FileSpreadsheet } from 'lucide-react'
import './EventTemplatesTab.css'
import '../pages/events.css'

import {
  useInvitationState,
  useQuickMode,
  useDesignMode,
  useTemplatePreview,
  LayoutSettings,
  QuickCountPanel,
  QuickNamesPanel,
  QuickExcelPanel,
  GenerateButton,
  TemplatePreviewModal,
  DesignModePanel,
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

  // ═══════════════════════════════════════════════════════════
  // Wizard: type → template (designed only) → guests → review
  // ═══════════════════════════════════════════════════════════
  type StepId = 'type' | 'template' | 'guests' | 'review'
  const steps: Array<{ id: StepId; title: string; hint: string }> = [
    { id: 'type', title: 'النوع', hint: 'شكل الدعوة وتأكيد الحضور' },
    ...(generationSource === 'design' ? [{ id: 'template' as StepId, title: 'القالب', hint: 'اختر التصميم' }] : []),
    { id: 'guests', title: 'الضيوف', hint: 'ملف أو أسماء أو عدد' },
    { id: 'review', title: 'المراجعة والإنشاء', hint: 'تأكد ثم أنشئ' },
  ]
  const [step, setStep] = useState<StepId>('type')
  const [furthestId, setFurthestId] = useState<StepId>('type')
  const stepIndex = Math.max(0, steps.findIndex(item => item.id === step))
  const furthest = Math.max(stepIndex, steps.findIndex(item => item.id === furthestId))
  const goTo = (id: StepId) => {
    setStep(id)
    if (steps.findIndex(item => item.id === id) > steps.findIndex(item => item.id === furthestId)) setFurthestId(id)
    window.requestAnimationFrame(() => document.querySelector('.inv-wizard__steps')?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }
  useEffect(() => {
    if (!steps.some(item => item.id === step)) setStep('type')
  }, [generationSource])
  // Counting cards cannot carry contact details, so RSVP needs names.
  useEffect(() => {
    if (!requireRsvp) return
    if (quickInputMode === 'manual') setQuickInputMode('names')
    if (state.designInputMode === 'count') state.setDesignInputMode('names')
  }, [requireRsvp])

  const serverReady = (importer: typeof serverImport) => (importer.state.summary?.valid ?? 0) > 0
  const guestCount = generationSource === 'quick'
    ? (quickInputMode === 'manual' ? vipCount + normalCount
      : quickInputMode === 'names' ? quickManualGuests.length
      : generationCaps?.enabled ? (serverImport.state.summary?.valid ?? 0) : excelImportedGuests.length)
    : (state.designInputMode === 'count' ? state.designCount
      : state.designInputMode === 'names' ? state.designManualGuests.length
      : generationCaps?.enabled ? (designedImport.state.summary?.valid ?? 0) : state.designExcelRows.length)
  const guestSummary = guestCount ? `${guestCount} ${state.designInputMode === 'count' && generationSource === 'design' || quickInputMode === 'manual' && generationSource === 'quick' ? 'دعوة' : 'ضيف'}` : '—'
  const guestsReady = generationSource === 'quick' && quickInputMode === 'excel' && generationCaps?.enabled
    ? serverReady(serverImport)
    : generationSource === 'design' && state.designInputMode === 'excel' && generationCaps?.enabled
      ? serverReady(designedImport)
      : guestCount > 0
  const blocker = step === 'template' && !designTemplateId ? 'اختر قالباً للمتابعة'
    : step === 'guests' && !guestsReady ? 'أضف الضيوف للمتابعة'
    : ''

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
          {/* ── Progress ── */}
          <ol className="inv-wizard__steps" aria-label="خطوات إنشاء الدعوات">
            {steps.map((item, index) => {
              const done = index < stepIndex
              const reachable = index <= furthest
              return (
                <li key={item.id} className={`inv-wizard__step${item.id === step ? ' is-current' : ''}${done ? ' is-done' : ''}`}>
                  <button type="button" disabled={!reachable} onClick={() => goTo(item.id)} aria-current={item.id === step ? 'step' : undefined}>
                    <span className="inv-wizard__dot">{done ? <Check size={14} /> : index + 1}</span>
                    <span className="inv-wizard__label"><strong>{item.title}</strong><small>{item.hint}</small></span>
                  </button>
                </li>
              )
            })}
          </ol>

          {/* ── ① Type ── */}
          {step === 'type' && (
            <div className="inv-wizard__panel">
              <h4 className="inv-wizard__q">ما نوع الدعوات التي تريد إنشاءها؟</h4>
              <div className="inv-wizard__choices">
                <button type="button" className={`inv-wizard__choice${generationSource === 'quick' ? ' is-active' : ''}`} onClick={() => setGenerationSource('quick')}>
                  <QrCode size={26} />
                  <strong>رمز دخول فقط</strong>
                  <span>بطاقات بسيطة فيها رمز QR لكل ضيف، جاهزة للطباعة أو الإرسال.</span>
                </button>
                <button type="button" className={`inv-wizard__choice${generationSource === 'design' ? ' is-active' : ''}`} onClick={() => setGenerationSource('design')}>
                  <Sparkles size={26} />
                  <strong>دعوة بتصميم مخصص</strong>
                  <span>تصميمك الخاص مع اسم الضيف ورمز الدخول مطبوعين على كل دعوة.</span>
                </button>
              </div>

              {state.rsvpEnabled && (
                <>
                  <h4 className="inv-wizard__q">هل تريد أن يؤكد الضيوف حضورهم قبل المناسبة؟</h4>
                  <div className="inv-wizard__choices">
                    <button type="button" className={`inv-wizard__choice inv-wizard__choice--sm${!requireRsvp ? ' is-active' : ''}`} onClick={() => setRequireRsvp(false)}>
                      <strong>لا، الدعوة صالحة للدخول مباشرة</strong>
                      <span>يكفي اسم الضيف، أو عدد الدعوات فقط.</span>
                    </button>
                    <button type="button" className={`inv-wizard__choice inv-wizard__choice--sm${requireRsvp ? ' is-active' : ''}`} onClick={() => setRequireRsvp(true)}>
                      <strong>نعم، يؤكد الضيف أولاً</strong>
                      <span>يصل الضيف رابط للرد، ويُفعَّل رمز دخوله بعد موافقته. يتطلب جوالاً أو بريداً لكل ضيف.</span>
                    </button>
                  </div>
                </>
              )}
            </div>
          )}

          {/* ── ② Template (designed invitations only) ── */}
          {step === 'template' && (
            <DesignModePanel
              step="template"
              serverImport={generationCaps?.enabled ? designedImport : undefined}
              maxCards={generationCaps?.max_cards}
              state={state}
              designMode={designMode}
              templatePreview={templatePreview}
              event={event}
              downloadExcelTemplate={downloadExcelTemplate}
            />
          )}

          {/* ── ③ Guests ── */}
          {step === 'guests' && generationSource === 'quick' && (
            <div className="inv-wizard__panel">
              {requireRsvp && <p className="inv-wizard__note"><Info size={15} /> فعّلت تأكيد الحضور: أضف جوالاً أو بريداً لكل ضيف.</p>}
          {generationSource === 'quick' && (
            <div className="inv-design-inner-tabs" style={{ marginTop: 8, marginBottom: 16 }}>
              <button
                type="button"
                className={`inv-design-inner-tab ${quickInputMode === 'manual' ? 'inv-design-inner-tab--active' : ''}`}
                onClick={() => setQuickInputMode('manual')}
                disabled={requireRsvp}
                title={requireRsvp ? 'تأكيد الحضور يحتاج اسماً وجوالاً أو بريداً لكل ضيف' : undefined}
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
            <ServerImportPanel importer={serverImport} requireRsvp={state.requireRsvp} onDownloadTemplate={downloadExcelTemplate} />
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

            </div>
          )}
          {step === 'guests' && generationSource === 'design' && (
            <DesignModePanel
              step="guests"
              serverImport={generationCaps?.enabled ? designedImport : undefined}
              maxCards={generationCaps?.max_cards}
              state={state}
              designMode={designMode}
              templatePreview={templatePreview}
              event={event}
              downloadExcelTemplate={downloadExcelTemplate}
            />
          )}

          {/* ── ④ Review & create ── */}
          {step === 'review' && (
            <div className="inv-wizard__panel">
              <dl className="inv-wizard__summary">
                <div><dt>النوع</dt><dd>{generationSource === 'design' ? 'دعوة بتصميم مخصص' : 'رمز دخول فقط'}</dd></div>
                {generationSource === 'design' && <div><dt>القالب</dt><dd>{state.selectedTemplate?.name ?? '—'}</dd></div>}
                <div><dt>الضيوف</dt><dd>{guestSummary}</dd></div>
                <div><dt>تأكيد الحضور</dt><dd>{requireRsvp ? 'مفعّل' : 'غير مفعّل'}</dd></div>
                <div><dt>الملفات</dt><dd>{state.canExport === false ? 'رموز فقط، دون PDF/ZIP' : 'PDF للطباعة + ZIP صور منفصلة'}</dd>
                  {state.canExport === false && <small className="inv-wizard__sub">ملفات الطباعة غير متاحة في باقتك الحالية أو لصلاحيتك.</small>}</div>
              </dl>
              {generationSource === 'quick' ? (
                <>
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
              ) : (
                  <DesignModePanel
              step="generate"
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
          )}

          {/* ── Navigation ── */}
          <div className="inv-wizard__nav">
            {stepIndex > 0 && <button type="button" className="inv-dl-btn" onClick={() => goTo(steps[stepIndex - 1].id)}><ChevronRight size={16} /> السابق</button>}
            {stepIndex < steps.length - 1 && (
              <>
                {blocker && <span className="inv-wizard__blocker">{blocker}</span>}
                <button type="button" className="inv-wizard__next" disabled={!!blocker} onClick={() => goTo(steps[stepIndex + 1].id)}>
                  التالي: {steps[stepIndex + 1].title} <ChevronLeft size={16} />
                </button>
              </>
            )}
          </div>
        </div>
      </section>

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
