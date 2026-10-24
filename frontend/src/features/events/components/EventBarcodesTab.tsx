import { DownloadFileButton } from '@components/DownloadFileButton'
import { LimitErrorNotice } from '@components/LimitErrorNotice'
import { useState, useMemo } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { EventModel, EventStats } from '../types'
import { useGenerateInvitations } from '../hooks/useGenerateInvitations'
import { invitationsApi, DEFAULT_LAYOUT, type LayoutConfig, type InvitationRead } from '../api/invitationsApi'
import {
  Printer, Download, Loader2, Grid3X3, ChevronDown, ChevronUp, Eye, EyeOff,
  FileText, Images, CheckCircle2, AlertCircle, Upload, FileSpreadsheet, X, Users, Sparkles, Copy
} from 'lucide-react'
import '../pages/events.css'
import { Can, PERM } from '@shared/permissions'
import { GenerationOperationTracker } from './invitations/GenerationOperationTracker'
import { LocalQrCode } from '@shared/components/LocalQrCode'
import { downloadAuthenticatedFile } from '@services/http/client'
import { GenerationHistoryTable } from './invitations/GenerationHistoryTable'
import { useGenerationCapabilities } from '../hooks/useGenerationOperations'
import { readSpreadsheet } from '../utils/spreadsheet'
import { downloadGuestTemplate } from '../utils/guestTemplate'

interface Props {
  event: EventModel
  stats?: EventStats
  onlyHistory?: boolean
}

export function EventBarcodesTab({ event, stats, onlyHistory = false }: Props) {
  const { data: generationCaps } = useGenerationCapabilities()
  const [vipCount, setVipCount] = useState(0)
  const [normalCount, setNormalCount] = useState(0)
  const [guestPrefix, setGuestPrefix] = useState('ضيف')
  const [generationSource, setGenerationSource] = useState<'manual' | 'excel'>('manual')
  const [importedGuests, setImportedGuests] = useState<any[]>([])
  const [importFileName, setImportFileName] = useState('')
  const [importErrors, setImportErrors] = useState<string[]>([])
  const [showSettings, setShowSettings] = useState(false)
  const [layout, setLayout] = useState<LayoutConfig>({ ...DEFAULT_LAYOUT })
  const { mutate: generate, isPending, data, isError, error } = useGenerateInvitations()
  const [localError, setLocalError] = useState<unknown>(null)

  // Generation history (shown in the Barcodes tab)
  const queryClient = useQueryClient()

  const {
    data: generationHistory = [],
    isLoading: isHistoryLoading,
    isFetching: isHistoryFetching,
    refetch: refetchHistory,
  } = useQuery({
    queryKey: ['fast-generation-history', event.id],
    queryFn: () => invitationsApi.getGenerationHistory(event.id),
    staleTime: 30_000,
  })

  const { mutate: deleteOperation, isPending: isDeletingOperation, variables: deletingOperationId } = useMutation({
    mutationFn: (operationId: string) => invitationsApi.deleteGenerationOperation(event.id, operationId),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['fast-generation-history', event.id] })
      queryClient.invalidateQueries({ queryKey: ['event-stats', event.id] })
      queryClient.invalidateQueries({ queryKey: ['events'] })
      if (data?.message) {
        alert(data.message)
      } else {
        alert('تم إلغاء وحذف عملية الإنشاء بنجاح')
      }
    },
    onError: (err: any) => {
      setLocalError(err)
    },
  })

  const [selectedOperation, setSelectedOperation] = useState<string | null>(null)
  const [filterQuery, setFilterQuery] = useState('')
  const [filterTicketClass, setFilterTicketClass] = useState<'all' | 'vip' | 'normal'>('all')
  const [filterStatus, setFilterStatus] = useState<'all' | string>('all')
  const [generateFallbackQr, setGenerateFallbackQr] = useState(true)

  const closeOperationDetails = () => setSelectedOperation(null)

  // Fetch invitations for the selected generation operation
  const {
    data: operationInvitations = [],
    isLoading: isOperationLoading,
  } = useQuery<InvitationRead[]>({
    queryKey: ['fast-generation-operation', event.id, selectedOperation],
    queryFn: () => invitationsApi.getGenerationOperationDetails(event.id, selectedOperation!),
    enabled: !!selectedOperation,
  })

  const filteredInvitations = useMemo(() => {
    if (!operationInvitations || !operationInvitations.length) return [] as InvitationRead[]
    const q = filterQuery.trim().toLowerCase()
    return operationInvitations.filter((inv) => {
      if (filterTicketClass !== 'all' && inv.ticket_class !== filterTicketClass) return false
      if (filterStatus !== 'all' && (inv.status ?? '') !== filterStatus) return false
      if (q) {
        const hay = `${inv.guest_name ?? ''} ${inv.token ?? ''} ${inv.guest_whatsapp ?? ''} ${inv.guest_email ?? ''}`.toLowerCase()
        if (!hay.includes(q)) return false
      }
      return true
    })
  }, [operationInvitations, filterQuery, filterTicketClass, filterStatus])

  const downloadGeneratedFile = (url: string, fallbackName: string) => {
    void downloadAuthenticatedFile(url, fallbackName).catch((error) => {
      setLocalError(error)
    })
  }

  const exportCsv = () => {
    if (!filteredInvitations || filteredInvitations.length === 0) {
      alert('لا توجد بيانات للتصدير')
      return
    }
    const header = ['id', 'guest_name', 'ticket_class', 'status', 'guest_whatsapp', 'guest_phone', 'guest_email', 'token']
    const rows = filteredInvitations.map((inv) => header.map((h) => {
      const v = (inv as any)[h] ?? ''
      return `"${String(v).replace(/"/g, '""')}"`
    }).join(','))
    const csv = [header.join(','), ...rows].join('\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `invitations_${selectedOperation || 'export'}.csv`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  const remainingVip = Math.max(0, event.vip_quota - (stats?.vip_count || 0))
  const remainingNormal = Math.max(0, event.normal_quota - (stats?.normal_count || 0))

  const updateLayout = (patch: Partial<LayoutConfig>) => setLayout((prev) => ({ ...prev, ...patch }))

  const downloadExcelTemplate = async () => {
    await downloadGuestTemplate({ title: event.title })
  }

  const clearImportedGuests = () => {
    setImportedGuests([])
    setImportFileName('')
    setImportErrors([])
  }

  const parseTicketClass = (value: unknown): 'vip' | 'normal' => {
    const normalized = String(value ?? '').trim().toLowerCase()
    if (['vip', 'v', 'كبار الشخصيات'].includes(normalized)) return 'vip'
    return 'normal'
  }

  const handleGuestFileSelected = async (file: File | null) => {
    if (!file) return
    setLocalError(null)
    setImportErrors([])

    try {
      const rows = await readSpreadsheet(file)

      const parsedRows: any[] = []
      const errors: string[] = []

      rows.forEach((row, index) => {
        const guestName = String(row['اسم الضيف'] ?? row['guest_name'] ?? row['name'] ?? '').trim()
        const invitationCountRaw = row['عدد الأشخاص'] ?? row['عدد الدعوات'] ?? row['invitation_count'] ?? row['count'] ?? 1
        const invitationCount = Number(invitationCountRaw)
        const ticketClass = parseTicketClass(row['نوع التذكرة'] ?? row['ticket_class'] ?? row['class'])

        if (!guestName) {
          errors.push(`السطر ${index + 2}: اسم الضيف مفقود`)
          return
        }
        if (!Number.isFinite(invitationCount) || invitationCount < 1 || invitationCount > 100) {
          errors.push(`السطر ${index + 2}: عدد الدعوات يجب أن يكون بين 1 و100`)
          return
        }

        parsedRows.push({ guest_name: guestName, invitation_count: Math.floor(invitationCount), ticket_class: ticketClass })
      })

      if (!parsedRows.length) {
        setImportErrors(errors.length ? errors : ['لم يتم العثور على صفوف صالحة داخل الملف'])
        setImportedGuests([])
        setImportFileName(file.name)
        return
      }

      setImportedGuests(parsedRows)
      setImportFileName(file.name)
      setImportErrors(errors)
      setGenerationSource('excel')
    } catch {
      setImportedGuests([])
      setImportFileName(file.name)
      setImportErrors(['تعذر قراءة الملف. استخدم ملف XLSX أو CSV'])
    }
  }

  const handleGenerate = () => {
    if (generationSource === 'excel' && importedGuests.length === 0) return
    if (generationSource === 'manual' && vipCount === 0 && normalCount === 0) return
    setLocalError(null)

    const invitations: Array<{ guest_name?: string; ticket_class: 'vip' | 'normal' }> = []
    if (generationSource === 'excel') {
      importedGuests.forEach((guest) => {
        for (let i = 0; i < guest.invitation_count; i++) {
          invitations.push({ guest_name: guest.guest_name, ticket_class: guest.ticket_class })
        }
      })
    } else {
      for (let i = 0; i < vipCount; i++) invitations.push({ guest_name: `${guestPrefix} VIP ${i + 1}`, ticket_class: 'vip' as const })
      for (let i = 0; i < normalCount; i++) invitations.push({ guest_name: `${guestPrefix} ${i + 1}`, ticket_class: 'normal' as const })
    }

    generate(
      {
        event_id: event.id,
        invitations,
        source_kind: generationSource === 'excel' ? 'excel' : 'count',
        count: { vip_count: vipCount, normal_count: normalCount, guest_name_prefix: guestPrefix },
        original_filename: generationSource === 'excel' ? importFileName || undefined : undefined,
        generate_pdf: true,
        generate_zip: true,
        upload_individual_barcodes: false,
        layout_config: { ...layout, show_code_text: false, show_guest_name: false },
      },
      { onError: (err: any) => setLocalError(err) },
    )
  }

  const importedVipCount = importedGuests.reduce((sum, guest) => sum + (guest.ticket_class === 'vip' ? guest.invitation_count : 0), 0)
  const importedNormalCount = importedGuests.reduce((sum, guest) => sum + (guest.ticket_class === 'normal' ? guest.invitation_count : 0), 0)
  const plannedVipCount = generationSource === 'excel' ? importedVipCount : vipCount
  const plannedNormalCount = generationSource === 'excel' ? importedNormalCount : normalCount
  const totalInvitations = plannedVipCount + plannedNormalCount
  const isFormValid = (plannedVipCount > 0 || plannedNormalCount > 0) && plannedVipCount <= remainingVip && plannedNormalCount <= remainingNormal
  const barcodePerPage = layout.rows * layout.cols
  const estimatedPages = totalInvitations > 0 ? Math.ceil(totalInvitations / barcodePerPage) : 0
  const formatGeneratedAt = (value: string | null) => {
    if (!value) return 'غير محدد'
    return new Intl.DateTimeFormat('ar', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
  }

  // handleDeleteOperation removed (history tab handles deletion)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      {!onlyHistory && (
        <>
          {/* Generation Card (same as in invitations tab) */}
          <section className="inv-card">
            <div className="inv-card__header">
              <div className="inv-card__icon inv-card__icon--gold"><Printer size={20} /></div>
              <div>
                <h3 className="inv-card__title">إنشاء الدعوات للطباعة</h3>
                <p className="inv-card__desc">إنشاء ملفات PDF و ZIP للدعوات الجاهزة للطباعة</p>
              </div>
            </div>
            <div className="inv-card__body">
              <div className="inv-source-switch">
                <button type="button" className={`inv-source-switch__btn ${generationSource === 'manual' ? 'inv-source-switch__btn--active' : ''}`} onClick={() => setGenerationSource('manual')}>
                  <Users size={15} /> إدخال يدوي
                </button>
                <button type="button" className={`inv-source-switch__btn ${generationSource === 'excel' ? 'inv-source-switch__btn--active' : ''}`} onClick={() => setGenerationSource('excel')}>
                  <FileSpreadsheet size={15} /> من ملف Excel
                </button>
              </div>

              {generationSource === 'manual' && (
                <>
                  <div className="inv-grid-2">
                    <div className="inv-tier-box inv-tier-box--vip">
                      <div className="inv-tier-box__glow" />
                      <div className="inv-tier-box__head">
                        <span className="inv-tier-box__label inv-tier-box__label--vip"><Sparkles size={15} /> تذاكر VIP</span>
                        <span className="inv-tier-box__badge inv-tier-box__badge--vip">المتبقي: {remainingVip}</span>
                      </div>
                      <label className="inv-label">عدد الدعوات المطلوب إنشاؤها</label>
                      <input type="number" min={0} max={remainingVip} value={vipCount || ''} onChange={(e) => setVipCount(parseInt(e.target.value) || 0)} className="inv-input" placeholder="0" disabled={isPending} />
                    </div>
                    <div className="inv-tier-box inv-tier-box--normal">
                      <div className="inv-tier-box__head">
                        <span className="inv-tier-box__label"><Users size={15} /> تذاكر الدخول العادي</span>
                        <span className="inv-tier-box__badge">المتبقي: {remainingNormal}</span>
                      </div>
                      <label className="inv-label">عدد الدعوات المطلوب إنشاؤها</label>
                      <input type="number" min={0} max={remainingNormal} value={normalCount || ''} onChange={(e) => setNormalCount(parseInt(e.target.value) || 0)} className="inv-input" placeholder="0" disabled={isPending} />
                    </div>
                  </div>
                  <div style={{ maxWidth: 400, marginBottom: 8 }}>
                    <label className="inv-label">بادئة اسم الضيف (مثال: ضيف 1، ضيف 2)</label>
                    <input type="text" value={guestPrefix} onChange={(e) => setGuestPrefix(e.target.value)} className="inv-input" placeholder="ضيف" disabled={isPending} />
                  </div>
                </>
              )}

              {generationSource === 'excel' && (
                <div className="inv-import-card">
                  <div className="inv-import-card__header">
                    <div>
                      <strong>رفع ملف الضيوف</strong>
                      <span>ارفع ملف Excel يحتوي على اسم الضيف، عدد الدعوات، ونوع التذكرة</span>
                    </div>
                    <button type="button" className="inv-dl-btn inv-dl-btn--zip" onClick={() => { void downloadExcelTemplate() }}><Download size={15} /> تنزيل النموذج</button>
                  </div>
                  <div className="inv-import-card__actions">
                    <label className="inv-upload-btn">
                      <Upload size={15} /> اختيار ملف Excel
                      <input type="file" accept=".xlsx,.csv" onClick={(e) => { e.currentTarget.value = '' }} onChange={(e) => handleGuestFileSelected(e.target.files?.[0] ?? null)} hidden />
                    </label>
                    {importFileName && (
                      <div className="inv-upload-file"><FileSpreadsheet size={15} /><span>{importFileName}</span><button type="button" className="inv-upload-file__clear" onClick={clearImportedGuests}><X size={14} /></button></div>
                    )}
                  </div>
                  {!!importErrors.length && (
                    <div className="inv-import-errors">{importErrors.slice(0, 5).map((msg) => (<div key={msg} className="inv-import-errors__item">{msg}</div>))}</div>
                  )}
                  {!!importedGuests.length && (
                    <>
                      <div className="inv-import-stats">
                        <div><strong>{importedGuests.length}</strong><span>ضيف/صف</span></div>
                        <div><strong>{importedVipCount}</strong><span>دعوات VIP</span></div>
                        <div><strong>{importedNormalCount}</strong><span>دعوات عادية</span></div>
                        <div><strong>{totalInvitations}</strong><span>إجمالي الدعوات</span></div>
                      </div>
                      <div className="inv-import-preview">{importedGuests.slice(0, 5).map((guest, index) => (<div key={`${guest.guest_name}-${index}`} className="inv-import-preview__row"><strong>{guest.guest_name}</strong><span>{guest.ticket_class === 'vip' ? 'VIP' : 'عادي'} · {guest.invitation_count} دعوة</span></div>))}{importedGuests.length > 5 && (<div className="inv-import-preview__more">+{importedGuests.length - 5} صفوف إضافية</div>)}</div>
                    </>
                  )}
                </div>
              )}

              <div className="inv-settings-panel">
                <button className="inv-settings-toggle" onClick={() => setShowSettings(!showSettings)}>
                  <div className="inv-settings-toggle__right">
                    <Grid3X3 size={14} style={{ opacity: 0.7 }} />
                    <span>إعدادات الطباعة</span>
                    {totalInvitations > 0 && (<span className="inv-settings-tag">{layout.rows}×{layout.cols} · {estimatedPages} صفحة</span>)}
                  </div>
                  {showSettings ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                </button>

                {showSettings && (
                  <div className="inv-settings-body">
                    <div>
                      <label className="inv-label" style={{ display: 'flex', alignItems: 'center', gap: 6 }}><Grid3X3 size={14} style={{ opacity: 0.7 }} /> حجم الشبكة (صفوف × أعمدة)</label>
                      <div className="inv-chip-group">
                        {[{ label: '3×3', rows: 3, cols: 3 }, { label: '4×4', rows: 4, cols: 4 }, { label: '5×5', rows: 5, cols: 5 }].map((p) => (
                          <button key={p.label} className={`inv-chip ${layout.rows === p.rows && layout.cols === p.cols ? 'inv-chip--active' : ''}`} onClick={() => updateLayout({ rows: p.rows, cols: p.cols })}>{p.label}</button>
                        ))}
                      </div>
                      <div className="inv-custom-grid"><div className="inv-custom-grid__field"><span>صفوف</span><input type="number" min={1} max={20} value={layout.rows} onChange={(e) => updateLayout({ rows: Math.max(1, Math.min(20, parseInt(e.target.value) || 1)) })} className="inv-input inv-input--sm" /></div><span className="inv-custom-grid__sep">×</span><div className="inv-custom-grid__field"><span>أعمدة</span><input type="number" min={1} max={20} value={layout.cols} onChange={(e) => updateLayout({ cols: Math.max(1, Math.min(20, parseInt(e.target.value) || 1)) })} className="inv-input inv-input--sm" /></div><span className="inv-custom-grid__info">= {barcodePerPage} دعوات/صفحة</span></div>
                    </div>
                    <div>
                      <label className="inv-label">حجم صورة رمز QR (بكسل)</label>
                      <div className="inv-chip-group">
                        {[{ label: 'تلقائي', value: null }, { label: '200px', value: 200 }, { label: '300px', value: 300 }, { label: '400px', value: 400 }].map((s) => (
                          <button key={s.label} className={`inv-chip ${layout.barcode_size_px === s.value ? 'inv-chip--active' : ''}`} onClick={() => updateLayout({ barcode_size_px: s.value })}>{s.label}</button>
                        ))}
                      </div>
                    </div>
                    <div className="inv-grid-2"><div><label className="inv-label">حجم الصفحة</label><select value={layout.page_size} onChange={(e) => updateLayout({ page_size: e.target.value as 'A4' | 'Letter' })} className="inv-input"><option value="A4">A4</option><option value="Letter">Letter</option></select></div><div><label className="inv-label">الاتجاه</label><select value={layout.orientation} onChange={(e) => updateLayout({ orientation: e.target.value as 'portrait' | 'landscape' })} className="inv-input"><option value="portrait">عمودي (Portrait)</option><option value="landscape">أفقي (Landscape)</option></select></div></div>
                    <div className="inv-toggle-row"><button className={`inv-toggle-btn ${layout.show_guest_name ? 'inv-toggle-btn--on' : ''}`} onClick={() => updateLayout({ show_guest_name: !layout.show_guest_name })}>{layout.show_guest_name ? <Eye size={14} /> : <EyeOff size={14} />} اسم الضيف</button><button className={`inv-toggle-btn ${layout.show_code_text ? 'inv-toggle-btn--on' : ''}`} onClick={() => updateLayout({ show_code_text: !layout.show_code_text })}>{layout.show_code_text ? <Eye size={14} /> : <EyeOff size={14} />} رمز الدعوة</button></div>
                    {totalInvitations > 0 && (<div className="inv-summary-bar"><span><strong>{totalInvitations}</strong> دعوة</span><span className="inv-summary-bar__dot" /><span><strong>{layout.rows}×{layout.cols}</strong> شبكة</span><span className="inv-summary-bar__dot" /><span><strong>{estimatedPages}</strong> صفحة</span><span className="inv-summary-bar__dot" /><span>رمز QR: <strong>{layout.barcode_size_px ? `${layout.barcode_size_px}px` : 'تلقائي'}</strong></span></div>)}
                  </div>
                )}
              </div>

              <Can permission={PERM.INV_GENERATE}>
                <button onClick={handleGenerate} disabled={!isFormValid || isPending} className="inv-generate-btn">{isPending ? (<><Loader2 size={18} className="animate-spin" /> جاري إنشاء الدعوات...</>) : (<><Printer size={18} /> إنشاء الدعوات ({totalInvitations} دعوة)</>)}</button>
              </Can>

              <LimitErrorNotice error={localError || (isError ? error : null)} />
            </div>
            {data?.operation && <GenerationOperationTracker operationId={data.operation.id} />}
            {data?.success && (<div className="inv-result"><div className="inv-result__info"><CheckCircle2 size={20} /><div><strong>تم إنشاء الدعوات بنجاح!</strong><span>{data.total_invitations} دعوة في {data.generation_time_ms}ms</span></div></div><Can permission={PERM.BATCH_DOWNLOAD}><div className="inv-result__actions">{data.pdf_url && (<DownloadFileButton url={data.pdf_url} filename="invitations.pdf" className="inv-dl-btn inv-dl-btn--pdf"><Download size={16} /> PDF ({data.pdf_size_mb?.toFixed(2)} MB)</DownloadFileButton>)}{data.zip_url && (<DownloadFileButton url={data.zip_url} filename="invitations.zip" className="inv-dl-btn inv-dl-btn--zip"><Download size={16} /> ZIP ({data.zip_size_mb?.toFixed(2)} MB)</DownloadFileButton>)}</div></Can></div>)}
          </section>
        </>
      )}

      <GenerationHistoryTable
        eventId={event.id}
        operationsEnabled={generationCaps?.enabled === true}
        history={generationHistory}
        loading={isHistoryLoading}
        fetching={isHistoryFetching}
        onRefresh={() => { void refetchHistory() }}
        onDetails={setSelectedOperation}
        deletingId={isDeletingOperation ? (deletingOperationId ?? null) : null}
        onDownload={downloadGeneratedFile}
        formatDate={formatGeneratedAt}
        onDelete={(item) => {
          const isRegistration = item.id === 'registration_submissions'
          const isRsvp = item.id === 'rsvp_submissions'
          const isDesigned = !isRegistration && !isRsvp && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(item.id)
          const confirmMsg = isRegistration
            ? 'هل أنت متأكد من إلغاء وحذف جميع دعوات التسجيل الذاتي لضيوف هذا النموذج؟'
            : isRsvp
            ? 'هل أنت متأكد من إلغاء وحذف جميع دعوات تأكيد الحضور؟'
            : isDesigned
            ? 'هل أنت متأكد من حذف دفعة إنشاء التصميم المخصص وإلغاء دعواتها؟'
            : 'هل أنت متأكد من حذف عملية الإنشاء هذه؟'
          if (window.confirm(confirmMsg)) deleteOperation(item.id)
        }}
      />

            {/* Operation details modal */}
            {selectedOperation && (
              <div className="inv-modal-overlay" role="dialog" aria-modal="true" onClick={closeOperationDetails}>
                <div className="inv-modal inv-modal--large" onClick={(e) => e.stopPropagation()}>

                  {/* Modern Header */}
                  <div className="inv-modal__header-premium">
                    <div className="inv-modal__title-premium">
                      <h3>تفاصيل عملية الإنشاء</h3>
                      <p className="inv-modal__subtitle">إدارة ومتابعة كروت الدعوة والباركودات الصادرة لهذه الدفعة</p>
                    </div>
                    <button className="inv-modal__close-premium" onClick={closeOperationDetails} title="إغلاق">
                      <X size={18} />
                    </button>
                  </div>

                  <div className="inv-modal__body">

                    {/* Stats & Filters Bar */}
                    <div className="inv-modal__filter-bar">
                      <div className="filter-search-wrapper">
                        <input
                          placeholder="بحث باسم الضيف أو التوكن أو جهة اتصال"
                          value={filterQuery}
                          onChange={(e) => setFilterQuery(e.target.value)}
                          className="inv-modal__search-input"
                        />
                      </div>

                      <div className="filter-controls-wrapper">
                        <div className="filter-select-group">
                          <label>الفئة:</label>
                          <select value={filterTicketClass} onChange={(e) => setFilterTicketClass(e.target.value as any)} className="inv-modal__select">
                            <option value="all">الكل</option>
                            <option value="vip">VIP</option>
                            <option value="normal">عادي</option>
                          </select>
                        </div>

                        <div className="filter-select-group">
                          <label>الحالة:</label>
                          <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)} className="inv-modal__select">
                            <option value="all">الكل</option>
                            {Array.from(new Set(operationInvitations.map((i) => i.status).filter(Boolean))).map((s) => {
                              const arStatus = s === 'created' ? 'تم الإنشاء' : s === 'accepted' ? 'مقبول' : s === 'viewed' ? 'تمت المشاهدة' : s === 'checked_in' ? 'تم الحضور' : s;
                              return <option key={s} value={s}>{arStatus}</option>;
                            })}
                          </select>
                        </div>

                        <div className="action-buttons-group">
                          <button
                            type="button"
                            className={`inv-modal__action-btn ${generateFallbackQr ? 'active' : ''}`}
                            title={generateFallbackQr ? 'إيقاف عرض الـ QR الاحتياطي' : 'عرض الـ QR الاحتياطي'}
                            onClick={() => setGenerateFallbackQr((v) => !v)}
                          >
                            {generateFallbackQr ? <Eye size={15} /> : <EyeOff size={15} />}
                            <span>QR احتياطي</span>
                          </button>

                          <Can permission={PERM.INV_EXPORT}>
                            <button
                              type="button"
                              className="inv-modal__action-btn"
                              title="تصدير البيانات إلى CSV"
                              onClick={exportCsv}
                            >
                              <Download size={15} />
                              <span>تصدير CSV</span>
                            </button>
                          </Can>
                        </div>
                      </div>
                    </div>

                    {/* Stats Summary Panel */}
                    <div className="inv-modal__stats-panel">
                      <div className="stat-pill total">
                        <span className="label">إجمالي الدعوات:</span>
                        <span className="value">{operationInvitations.length}</span>
                      </div>
                      <div className="stat-pill filtered">
                        <span className="label">المطابقة للبحث:</span>
                        <span className="value">{filteredInvitations.length}</span>
                      </div>

                      {/* Show PDF/ZIP links directly inside this stats panel */}
                      <Can permission={PERM.BATCH_DOWNLOAD}>
                      <div className="file-downloads-group">
                        {generationHistory.find((h) => h.id === selectedOperation)?.pdf_url && (
                          <DownloadFileButton url={generationHistory.find((h) => h.id === selectedOperation)!.pdf_url!} filename="invitations.pdf" className="inv-modal__download-file-btn pdf">
                            <FileText size={14} />
                            <span>تنزيل PDF</span>
                          </DownloadFileButton>
                        )}
                        {generationHistory.find((h) => h.id === selectedOperation)?.zip_url && (
                          <DownloadFileButton url={generationHistory.find((h) => h.id === selectedOperation)!.zip_url!} filename="invitations.zip" className="inv-modal__download-file-btn zip">
                            <Images size={14} />
                            <span>تنزيل ZIP</span>
                          </DownloadFileButton>
                        )}
                      </div>
                      </Can>
                    </div>

                    {isOperationLoading ? (
                      <div className="center-loader">
                        <Loader2 size={24} className="animate-spin" />
                        <span>جاري تحميل بيانات المدعوين...</span>
                      </div>
                    ) : filteredInvitations.length === 0 ? (
                      <div className="inv-modal__empty-state">
                        <AlertCircle size={32} />
                        <span>لم يتم العثور على أي نتائج تطابق خيارات البحث الحالية.</span>
                      </div>
                    ) : (
                      <div className="inv-modal__table-container">
                        <table className="inv-modal__table">
                          <thead>
                            <tr>
                              <th>الرمز (QR)</th>
                              <th>بيانات الضيف</th>
                              <th>جهة الاتصال</th>
                              <th>رابط الدعوة والإجراءات</th>
                            </tr>
                          </thead>
                          <tbody>
                            {filteredInvitations.map((inv) => {
                              const isVip = inv.ticket_class === 'vip';
                              const status = inv.status;
                              let statusLabel = status;
                              let statusClass = 'status-default';
                              if (status === 'created') {
                                statusLabel = 'تم الإنشاء';
                                statusClass = 'status-created';
                              } else if (status === 'accepted') {
                                statusLabel = 'مقبول';
                                statusClass = 'status-accepted';
                              } else if (status === 'viewed') {
                                statusLabel = 'تمت المشاهدة';
                                statusClass = 'status-viewed';
                              } else if (status === 'checked_in') {
                                statusLabel = 'تم الحضور';
                                statusClass = 'status-checked-in';
                              }

                              return (
                                <tr key={inv.id}>
                                  <td>
                                    <div className="qr-preview-wrapper">
                                      {inv.barcode_png_url ? (
                                        <img src={inv.barcode_png_url} alt="qr" className="qr-preview-img" />
                                      ) : generateFallbackQr && inv.token ? (
                                        <LocalQrCode
                                          value={inv.token}
                                          size={layout.barcode_size_px || 200}
                                          alt="qr"
                                          className="qr-preview-img"
                                        />
                                      ) : (
                                        <div className="qr-preview-empty">بلا رمز</div>
                                      )}
                                    </div>
                                  </td>
                                  <td>
                                    <div className="guest-info-cell">
                                      <strong className="guest-name">{inv.guest_name ?? '—'}</strong>
                                      <div className="guest-badges">
                                        <span className={`class-badge ${isVip ? 'vip' : 'normal'}`}>
                                          {isVip ? '👑 VIP' : '🎫 عادي'}
                                        </span>
                                        {status && (
                                          <span className={`status-badge ${statusClass}`}>
                                            {statusLabel}
                                          </span>
                                        )}
                                      </div>
                                    </div>
                                  </td>
                                  <td>
                                    <div className="contact-info-cell">
                                      {inv.guest_whatsapp || inv.guest_phone || inv.guest_email ? (
                                        <>
                                          {inv.guest_whatsapp && <span className="contact-item whatsapp">💬 {inv.guest_whatsapp}</span>}
                                          {inv.guest_phone && !inv.guest_whatsapp && <span className="contact-item phone">📞 {inv.guest_phone}</span>}
                                          {inv.guest_email && <span className="contact-item email">📧 {inv.guest_email}</span>}
                                        </>
                                      ) : (
                                        <span className="text-muted">—</span>
                                      )}
                                    </div>
                                  </td>
                                  <td>
                                    {inv.token ? (
                                      <div className="action-buttons-cell">
                                        <button
                                          className="action-btn copy"
                                          onClick={() => {
                                            const url = `${window.location.origin}/i/${inv.token}`
                                            navigator.clipboard?.writeText(url)
                                            alert('تم نسخ رابط الدعوة بنجاح!')
                                          }}
                                          title="نسخ رابط الدعوة"
                                        >
                                          <Copy size={13} />
                                          <span>نسخ الرابط</span>
                                        </button>
                                        <a
                                          href={`/i/${inv.token}`}
                                          target="_blank"
                                          rel="noreferrer"
                                          className="action-btn view"
                                          title="عرض صفحة الدعوة"
                                        >
                                          <Eye size={13} />
                                          <span>عرض</span>
                                        </a>
                                      </div>
                                    ) : (
                                      <span className="text-muted">—</span>
                                    )}
                                  </td>
                                </tr>
                              )
                            })}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
    </div>
  )
}

export default EventBarcodesTab
