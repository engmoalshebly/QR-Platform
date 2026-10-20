import { getApiErrorMessage, getApiErrorCode } from '@services/http/client'
/**
 * useInvitationState.ts
 * Central state management hook for the invitation generation system.
 * Consolidates ~40 useState declarations from EventInvitationsTab.tsx.
 */
import { useState, useMemo, useEffect } from 'react'
import { usePermission } from '@shared/permissions'
import { useQuery, useQueries, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { EventModel, EventStats } from '../../../types'
import { DEFAULT_LAYOUT, type LayoutConfig } from '../../../api/invitationsApi'
import { batchesApi, type BatchLayoutConfig } from '../../../api/batchesApi'
import { templatesApi } from '../../../api/templatesApi'
import { useGenerateInvitations } from '../../../hooks/useGenerateInvitations'
import type {
  GenerationSource,
  QuickInputMode,
  DesignInputMode,
  GuestImportRow,
  DesignExcelColumn,
  DynamicField,
} from '../types'
import { BUILTIN_FIELDS } from '../types'
import { http } from '@services/http/client'
import { useAuthStore } from '@features/auth/store/authStore'

export function useInvitationState(event: EventModel, stats?: EventStats) {
  const hasExportPermission = usePermission('invitations.export')
  const queryClient = useQueryClient()
  const tenantId = useAuthStore(s => s.currentTenantId)
  const { data: rsvpAvailability } = useQuery({
    queryKey: ['feature-availability', tenantId, 'rsvp'],
    queryFn: () => http.get<{ enabled: boolean }>('/tenants/current/features/rsvp/availability').then(r => r.data),
    enabled: !!tenantId,
    staleTime: 0,
  })
  const rsvpEnabled = rsvpAvailability?.enabled === true
  const { data: exportAvailability } = useQuery({
    queryKey: ['feature-availability', tenantId, 'pdf_export'],
    queryFn: () => http.get<{ enabled: boolean }>('/tenants/current/features/pdf_export/availability').then(r => r.data),
    enabled: !!tenantId && hasExportPermission,
    staleTime: 0,
  })
  const canExport = hasExportPermission && exportAvailability?.enabled !== false

  const [searchParams] = useSearchParams()

  // ── Storage keys ──
  const sourceStorageKey = `event-invitations-source:${event.id}`
  const designModeStorageKey = `event-invitations-design-mode:${event.id}`

  // ═══════════════════════════════════════════════════════════
  // Quick Mode State
  // ═══════════════════════════════════════════════════════════

  const [vipCount, setVipCount] = useState(0)
  const [normalCount, setNormalCount] = useState(0)
  const [guestPrefix, setGuestPrefix] = useState('ضيف')

  const [generationSource, setGenerationSource] = useState<GenerationSource>(() => {
    if (typeof window === 'undefined') return 'quick'
    const params = new URLSearchParams(window.location.search)
    if (params.get('templateId') || params.get('source') === 'design') return 'design'
    const saved = window.localStorage.getItem(sourceStorageKey)
    if (saved === 'manual' || saved === 'excel') return 'quick'
    return saved === 'design' ? 'design' : 'quick'
  })

  const [quickInputMode, setQuickInputMode] = useState<QuickInputMode>(() => {
    if (typeof window === 'undefined') return 'manual'
    const saved = window.localStorage.getItem(`event-invitations-quick-mode:${event.id}`)
    const oldSource = window.localStorage.getItem(sourceStorageKey)
    if (oldSource === 'excel') return 'excel'
    return saved === 'manual' || saved === 'names' || saved === 'excel' ? (saved as QuickInputMode) : 'manual'
  })

  // Excel import state
  const [excelImportedGuests, setExcelImportedGuests] = useState<GuestImportRow[]>([])
  const [excelImportFileName, setExcelImportFileName] = useState('')
  const [excelImportErrors, setExcelImportErrors] = useState<string[]>([])

  // Quick manual guest list
  const [quickManualGuests, setQuickManualGuests] = useState<GuestImportRow[]>(() => {
    if (typeof window === 'undefined') return []
    const saved = window.localStorage.getItem(`event-invitations-quick-manual:${event.id}`)
    return saved ? JSON.parse(saved) : []
  })

  // Quick form fields
  const [quickFormName, setQuickFormName] = useState('')
  const [quickFormCount, setQuickFormCount] = useState(1)
  const [quickFormClass, setQuickFormClass] = useState<'vip' | 'normal'>('normal')
  const [quickDynamicFields, setQuickDynamicFields] = useState<string[]>(() => {
    if (typeof window === 'undefined') return []
    const saved = window.localStorage.getItem(`event-invitations-quick-dynamic-fields:${event.id}`)
    return saved ? JSON.parse(saved) : []
  })
  const [newQuickFieldName, setNewQuickFieldName] = useState('')
  const [quickFormPhone, setQuickFormPhone] = useState('')
  const [quickFormEmail, setQuickFormEmail] = useState('')
  const [quickFormCustomFields, setQuickFormCustomFields] = useState<Record<string, string>>({})

  // ═══════════════════════════════════════════════════════════
  // Design Mode State
  // ═══════════════════════════════════════════════════════════

  const [designInputMode, setDesignInputMode] = useState<DesignInputMode>(() => {
    if (typeof window === 'undefined') return 'count'
    const saved = window.localStorage.getItem(designModeStorageKey)
    return saved === 'count' || saved === 'names' || saved === 'excel' ? (saved as DesignInputMode) : 'count'
  })
  const [designCount, setDesignCount] = useState(1)
  const [designTicketClass, setDesignTicketClass] = useState<'vip' | 'normal'>('normal')

  const initialTemplateId = searchParams.get('templateId') || ''
  const initialTicketClass = searchParams.get('ticketClass')
  const [designTemplateId, setDesignTemplateId] = useState(initialTemplateId)
  const [designTemplateName, setDesignTemplateName] = useState('')

  // Design manual guests
  const [designManualGuests, setDesignManualGuests] = useState<GuestImportRow[]>(() => {
    if (typeof window === 'undefined') return []
    const saved = window.localStorage.getItem(`event-invitations-design-manual:${event.id}`)
    return saved ? JSON.parse(saved) : []
  })
  const [designFormName, setDesignFormName] = useState('')
  const [designFormCount, setDesignFormCount] = useState(1)
  const [designFormPhone, setDesignFormPhone] = useState('')
  const [designFormEmail, setDesignFormEmail] = useState('')
  const [designFormCustomFields, setDesignFormCustomFields] = useState<Record<string, string>>({})

  // Design import state (legacy)
  const [designImportedGuests, setDesignImportedGuests] = useState<GuestImportRow[]>([])
  const [designImportFileName, setDesignImportFileName] = useState('')
  const [designImportErrors, setDesignImportErrors] = useState<string[]>([])
  void designImportErrors
  void designImportedGuests
  void designImportFileName

  // Design Excel flow state
  const [designExcelFile, setDesignExcelFile] = useState<File | null>(null)
  const [designExcelColumns, setDesignExcelColumns] = useState<DesignExcelColumn[]>([])
  const [designExcelRows, setDesignExcelRows] = useState<Record<string, string>[]>([])
  const [designColumnMapping, setDesignColumnMapping] = useState<Record<string, string>>({})
  const [designMappingErrors, setDesignMappingErrors] = useState<string[]>([])
  const [dynamicFields, setDynamicFields] = useState<DynamicField[]>(BUILTIN_FIELDS)
  const [designTemplateElements, setDesignTemplateElements] = useState<any[]>([])
  const [hoveredFieldKey, setHoveredFieldKey] = useState<string | null>(null)
  const [designExcelReady, setDesignExcelReady] = useState(false)
  const [isGeneratingDesigned, setIsGeneratingDesigned] = useState(false)
  const [designStatus, setDesignStatus] = useState<string | null>(null)
  const [designBatchId, setDesignBatchId] = useState('')
  const [designOperationId, setDesignOperationId] = useState('')

  // ═══════════════════════════════════════════════════════════
  // Shared State
  // ═══════════════════════════════════════════════════════════

  const [showSettings, setShowSettings] = useState(false)
  const [layout, setLayout] = useState<LayoutConfig>({ ...DEFAULT_LAYOUT })
  const [localErrorDetail, setLocalError] = useState<unknown>(null)
  const localError = localErrorDetail && !getApiErrorCode(localErrorDetail) ? (typeof localErrorDetail === 'string' ? localErrorDetail : getApiErrorMessage(localErrorDetail)) : null
  const [rsvpRequested, setRequireRsvp] = useState(false)
  const supportsRsvp = rsvpEnabled && (generationSource === 'design' ? designInputMode !== 'count' : quickInputMode !== 'manual')
  const requireRsvp = supportsRsvp && rsvpRequested
  useEffect(() => {
    if (!supportsRsvp) setRequireRsvp(false)
  }, [supportsRsvp])
  const [modalAlert, setModalAlert] = useState<{ title: string; message: string; type: 'success' | 'error' | 'info' } | null>(null)

  // Single guest modal
  const [singleGuestName, setSingleGuestName] = useState('')
  const [singleGuestCount, setSingleGuestCount] = useState(1)
  const [singleGuestClass, setSingleGuestClass] = useState<'vip' | 'normal'>('normal')
  const [showSingleGuestModal, setShowSingleGuestModal] = useState(false)

  // Preview state
  const [selectedTemplateForPreview, setSelectedTemplateForPreview] = useState<any>(null)
  const [showPreviewModal, setShowPreviewModal] = useState(false)
  const [activePreviewFields, setActivePreviewFields] = useState<any[]>([])
  const [previewData, setPreviewData] = useState<any>({
    guest_name: 'أحمد علي',
    guest_phone: '', guest_email: '',
    guest_company: '', guest_title: '',
    event_title: 'حفل تخرج',
    event_date: '2025-06-15', event_time: '19:00',
    event_location: 'فندق الريتز',
    seat_number: 'A12', table_number: '5',
    custom_data: {},
  })

  // ═══════════════════════════════════════════════════════════
  // Hooks & Queries
  // ═══════════════════════════════════════════════════════════

  const { mutate: generate, isPending, data, isError, error, reset } = useGenerateInvitations()

  const { data: templates = [], refetch: refetchTemplates, isLoading: isTemplatesLoading } = useQuery({
    queryKey: ['event-templates', event.id],
    queryFn: () => templatesApi.list(event.id),
  })

  const selectedTemplate = templates.find((t) => t.id === designTemplateId)

  const { data: designBatch } = useQuery({
    queryKey: ['design-batch', event.id, designBatchId],
    queryFn: () => batchesApi.get(designBatchId),
    enabled: !!designBatchId,
    refetchInterval: designBatchId ? 3000 : false,
  })

  // ═══════════════════════════════════════════════════════════
  // Computed Values
  // ═══════════════════════════════════════════════════════════

  const remainingVip = event.vip_quota === 0 ? Infinity : Math.max(0, event.vip_quota - (stats?.vip_quota_used ?? stats?.vip_count ?? 0))
  const remainingNormal = event.normal_quota === 0 ? Infinity : Math.max(0, event.normal_quota - (stats?.normal_quota_used ?? stats?.normal_count ?? 0))

  const importedVipCount = excelImportedGuests.reduce((sum, g) => sum + (g.ticket_class === 'vip' ? g.invitation_count : 0), 0)
  const importedNormalCount = excelImportedGuests.reduce((sum, g) => sum + (g.ticket_class === 'normal' ? g.invitation_count : 0), 0)
  const quickManualVipCount = quickManualGuests.reduce((sum, g) => sum + (g.ticket_class === 'vip' ? g.invitation_count : 0), 0)
  const quickManualNormalCount = quickManualGuests.reduce((sum, g) => sum + (g.ticket_class === 'normal' ? g.invitation_count : 0), 0)

  const plannedVipCount = generationSource === 'quick'
    ? quickInputMode === 'excel' ? importedVipCount
    : quickInputMode === 'names' ? quickManualVipCount
    : vipCount
    : 0

  const plannedNormalCount = generationSource === 'quick'
    ? quickInputMode === 'excel' ? importedNormalCount
    : quickInputMode === 'names' ? quickManualNormalCount
    : normalCount
    : 0

  const isFormValid = (stats !== undefined || (event.vip_quota === 0 && event.normal_quota === 0)) &&
    (quickInputMode !== 'excel' || excelImportErrors.length === 0) &&
    (quickInputMode !== 'manual' || (Number.isInteger(vipCount) && Number.isInteger(normalCount) && vipCount >= 0 && normalCount >= 0)) &&
    (quickInputMode === 'names' ? quickManualGuests.length : quickInputMode === 'excel' ? excelImportedGuests.length : vipCount + normalCount) <= 1000 && generationSource === 'quick'
    ? quickInputMode === 'names'
      ? quickManualGuests.length > 0 && plannedVipCount <= remainingVip && plannedNormalCount <= remainingNormal
      : quickInputMode === 'excel'
      ? excelImportedGuests.length > 0 && plannedVipCount <= remainingVip && plannedNormalCount <= remainingNormal
      : (vipCount > 0 || normalCount > 0) && plannedVipCount <= remainingVip && plannedNormalCount <= remainingNormal
    : false

  const barcodePerPage = layout.rows * layout.cols
  const totalPeople = plannedVipCount + plannedNormalCount
  const totalInvitations = quickInputMode === 'names' ? quickManualGuests.length : quickInputMode === 'excel' ? excelImportedGuests.length : vipCount + normalCount
  const estimatedPages = totalInvitations > 0 ? Math.ceil(totalInvitations / barcodePerPage) : 0

  const isBatchRunning = isGeneratingDesigned || (!!designBatchId && (!designBatch || ['queued', 'generating_barcodes', 'rendering_images', 'generating_pdf', 'generating_zip'].includes(designBatch.status)))
  const isBatchFailed = !!designBatchId && designBatch && designBatch.status === 'failed'
  const isBatchReady = !!designBatchId && designBatch && designBatch.status === 'ready'

  const isQuickRsvpMissingContact = useMemo(() => {
    if (!requireRsvp) return false
    if (quickInputMode === 'manual') return true
    return false
  }, [requireRsvp, quickInputMode])

  const isDesignRsvpMissingContact = useMemo(() => {
    if (!requireRsvp) return false
    if (designInputMode === 'count') return true
    return false
  }, [requireRsvp, designInputMode])

  // Designed templates with metadata
  const designedTemplates = useMemo(() => templates.filter((t) => t.template_type === 'designed'), [templates])
  const elementsQueries = useQueries({
    queries: designedTemplates.map((tpl) => ({
      queryKey: ['template-elements', tpl.id],
      queryFn: () => templatesApi.getElements(tpl.id),
      staleTime: 1000 * 60 * 5,
    })),
  })

  const designedTemplatesWithMetadata = useMemo(() => {
    return designedTemplates.map((tpl, index) => {
      const query = elementsQueries[index]
      const elements = query?.data || []
      const dynamicElements = elements.filter((el) => el.element_type === 'dynamic_text' || el.element_type === 'guest_name')
      return {
        template: tpl,
        isLoading: query ? query.isLoading : true,
        isError: query ? query.isError : false,
        hasDynamic: dynamicElements.length > 0,
        dynamicCount: dynamicElements.length,
      }
    })
  }, [designedTemplates, elementsQueries])

  const matchingDesignedTemplates = useMemo(() => {
    return designedTemplatesWithMetadata.filter((item) => item.template.ticket_class === designTicketClass)
  }, [designedTemplatesWithMetadata, designTicketClass])

  const designedLayout: BatchLayoutConfig = {
    page_size: 'A4', orientation: 'portrait',
    rows: 1, cols: 1,
    margin_top_mm: 0, margin_bottom_mm: 0,
    margin_left_mm: 0, margin_right_mm: 0,
    gap_x_mm: 0, gap_y_mm: 0,
    barcode_size_px: 420, barcode_size_mode: 'contain',
    show_code_text: false, show_guest_name: false,
    caption_field: 'none', dpi: 300,
    card_per_page: true, barcode_render: 'png',
    cell_padding_mm: 0,
  }

  // ═══════════════════════════════════════════════════════════
  // localStorage Persistence Effects
  // ═══════════════════════════════════════════════════════════

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(sourceStorageKey, generationSource)
  }, [generationSource, sourceStorageKey])

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(`event-invitations-quick-mode:${event.id}`, quickInputMode)
  }, [quickInputMode, event.id])

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(`event-invitations-quick-manual:${event.id}`, JSON.stringify(quickManualGuests))
  }, [quickManualGuests, event.id])

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(`event-invitations-quick-dynamic-fields:${event.id}`, JSON.stringify(quickDynamicFields))
  }, [quickDynamicFields, event.id])

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(`event-invitations-design-manual:${event.id}`, JSON.stringify(designManualGuests))
  }, [designManualGuests, event.id])

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(designModeStorageKey, designInputMode)
  }, [designInputMode, designModeStorageKey])

  // Clear success messages when switching tabs
  useEffect(() => {
    reset()
    setLocalError(null)
    setDesignBatchId('')
    setDesignOperationId('')
    setDesignStatus(null)
  }, [generationSource, reset])

  // Reset template when ticket class changes
  useEffect(() => {
    if (!designTemplateId) return
    const selected = templates.find((tpl) => tpl.id === designTemplateId)
    if (selected && selected.ticket_class !== designTicketClass) {
      setDesignTemplateId('')
      setDesignTemplateName('')
    }
  }, [designTicketClass, designTemplateId, templates])

  // Auto-select template from URL
  useEffect(() => {
    if (initialTemplateId && templates.length > 0) {
      const tpl = templates.find((t) => t.id === initialTemplateId)
      if (tpl && !designTemplateName) {
        setDesignTemplateName(tpl.name)
        if (tpl.ticket_class === 'vip' || tpl.ticket_class === 'normal') {
          setDesignTicketClass(tpl.ticket_class)
        } else if (initialTicketClass === 'vip' || initialTicketClass === 'normal') {
          setDesignTicketClass(initialTicketClass)
        }
        setDesignStatus(`تم تحديد القالب: ${tpl.name}`)
      }
    }
  }, [initialTemplateId, initialTicketClass, templates, designTemplateName])

  // Track batch status
  useEffect(() => {
    if (!designBatchId || !designBatch) return
    if (designBatch.status === 'ready' && designBatch.result_pdf_url) {
      setDesignStatus('اكتمل التوليد ويمكنك تنزيل الملفات الآن')
      queryClient.invalidateQueries({ queryKey: ['invitations'] })
      queryClient.invalidateQueries({ queryKey: ['event-stats', event.id] })
    } else if (designBatch.status === 'failed') {
      setDesignStatus('فشلت عملية التوليد')
    } else {
      setDesignStatus(`حالة الدفعة: ${designBatch.status} · %${designBatch.progress}`)
    }
  }, [designBatchId, designBatch, event.id, queryClient])

  // Helper
  const updateLayout = (patch: Partial<LayoutConfig>) =>
    setLayout((prev) => ({ ...prev, ...patch }))

  // ═══════════════════════════════════════════════════════════
  // Return all state & setters
  // ═══════════════════════════════════════════════════════════

  return {
    // Quick mode
    vipCount, setVipCount, normalCount, setNormalCount,
    guestPrefix, setGuestPrefix,
    generationSource, setGenerationSource,
    quickInputMode, setQuickInputMode,
    excelImportedGuests, setExcelImportedGuests,
    excelImportFileName, setExcelImportFileName,
    excelImportErrors, setExcelImportErrors,
    quickManualGuests, setQuickManualGuests,
    quickFormName, setQuickFormName,
    quickFormCount, setQuickFormCount,
    quickFormClass, setQuickFormClass,
    quickDynamicFields, setQuickDynamicFields,
    newQuickFieldName, setNewQuickFieldName,
    quickFormPhone, setQuickFormPhone,
    quickFormEmail, setQuickFormEmail,
    quickFormCustomFields, setQuickFormCustomFields,

    // Design mode
    designInputMode, setDesignInputMode,
    designCount, setDesignCount,
    designTicketClass, setDesignTicketClass,
    designTemplateId, setDesignTemplateId,
    designTemplateName, setDesignTemplateName,
    designManualGuests, setDesignManualGuests,
    designFormName, setDesignFormName,
    designFormCount, setDesignFormCount,
    designFormPhone, setDesignFormPhone,
    designFormEmail, setDesignFormEmail,
    designFormCustomFields, setDesignFormCustomFields,
    designExcelFile, setDesignExcelFile,
    designExcelColumns, setDesignExcelColumns,
    designExcelRows, setDesignExcelRows,
    designColumnMapping, setDesignColumnMapping,
    designMappingErrors, setDesignMappingErrors,
    dynamicFields, setDynamicFields,
    designTemplateElements, setDesignTemplateElements,
    hoveredFieldKey, setHoveredFieldKey,
    designExcelReady, setDesignExcelReady,
    isGeneratingDesigned, setIsGeneratingDesigned,
    designStatus, setDesignStatus,
    designBatchId, setDesignBatchId,
    designOperationId, setDesignOperationId,
    designedLayout,

    // Import legacy
    designImportedGuests, setDesignImportedGuests,
    designImportFileName, setDesignImportFileName,
    designImportErrors, setDesignImportErrors,

    // Shared
    showSettings, setShowSettings,
    layout, setLayout, updateLayout,
    localError, localErrorDetail, setLocalError,
    requireRsvp, setRequireRsvp, rsvpEnabled,
    modalAlert, setModalAlert,
    singleGuestName, setSingleGuestName,
    singleGuestCount, setSingleGuestCount,
    singleGuestClass, setSingleGuestClass,
    showSingleGuestModal, setShowSingleGuestModal,

    // Preview
    selectedTemplateForPreview, setSelectedTemplateForPreview,
    showPreviewModal, setShowPreviewModal,
    activePreviewFields, setActivePreviewFields,
    previewData, setPreviewData,

    // Hooks & queries
    generate, isPending, data, isError, error, reset, canExport, totalPeople,
    templates, refetchTemplates, selectedTemplate,
    isTemplatesLoading,
    designBatch,
    queryClient,

    // Computed
    remainingVip, remainingNormal,
    plannedVipCount, plannedNormalCount,
    isFormValid, barcodePerPage, totalInvitations, estimatedPages,
    isBatchRunning, isBatchFailed, isBatchReady,
    isQuickRsvpMissingContact, isDesignRsvpMissingContact,
    designedTemplates, designedTemplatesWithMetadata,
    matchingDesignedTemplates, elementsQueries,
  }
}

export type InvitationStateReturn = ReturnType<typeof useInvitationState>
