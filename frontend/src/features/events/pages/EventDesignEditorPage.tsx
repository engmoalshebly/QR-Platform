import { LimitErrorNotice } from '@components/LimitErrorNotice'
import { getApiErrorMessage } from '@services/http/client'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuthStore } from '@features/auth/store/authStore'
import { useEventDetail } from '../hooks/useEventDetails'
import { Upload, Save, Trash2, Move, QrCode, Eye, EyeOff, ArrowRight, Loader2, Type, AlignLeft, AlignCenter, AlignRight, Barcode, Database, Bold, ChevronDown, Image as ImageIcon } from 'lucide-react'
import QRCode from 'qrcode'
import { templatesApi, type TemplateElementCreateRequest, type TemplateElementType } from '../api/templatesApi'
import { WorkspaceShell } from '@features/workspace/components/WorkspaceShell'
import { Can, PERM, usePermission } from '@shared/permissions'
import { downloadSpreadsheet, readSpreadsheetHeaders } from '../utils/spreadsheet'
import { generateUUID } from '@shared/utils/uuid'
import './events.css'



type EditorElement = TemplateElementCreateRequest & {
  id: string
  x: number
  y: number
  width: number
  height: number
}

type PagePreset = 'A4' | 'Letter' | 'Custom'

type BackgroundTransform = {
  scale: number
  offsetX: number
  offsetY: number
  fitMode: 'contain' | 'cover' | 'manual'
}

type BackgroundFileKind = 'image' | 'pdf'
type AutoPageMode = 'auto' | 'a4' | 'letter'

type ElementPreset = { type: TemplateElementType; label: string; icon: typeof QrCode; excelOnly?: boolean; defaults: Partial<TemplateElementCreateRequest> }

// Fonts will be loaded dynamically from the backend list endpoint

const ELEMENT_PRESETS: ElementPreset[] = [
  {
    type: 'qr_code',
    label: 'باركود QR',
    icon: QrCode,
    defaults: { x: 0.5, y: 0.34, width: 0.20, height: 0.20, qr_size: 0.20, qr_error_level: 'M' },
  },
  {
    type: 'dynamic_text',
    label: 'نص ديناميكي',
    icon: Database,
    defaults: { x: 0.5, y: 0.15, width: 0.4, height: 0.029, font_size: 28, font_color: '#ffffff', text_align: 'center', data_key: '' },
  },
  {
    type: 'custom_text',
    label: 'نص ثابت',
    icon: AlignLeft,
    defaults: { x: 0.5, y: 0.28, width: 0.4, height: 0.021, font_size: 20, font_color: '#ffffff', text_align: 'center', static_content: 'نص تجريبي' },
  },
  {
    type: 'image',
    label: 'شعار / صورة',
    icon: ImageIcon,
    defaults: { x: 0.5, y: 0.5, width: 0.15, height: 0.15, static_content: '' },
  },
]


function createDefaultElement(type: TemplateElementType, index: number): EditorElement {
  const preset = ELEMENT_PRESETS.find((item) => item.type === type)
  const defaults = preset?.defaults ?? {}
  return {
    id: generateUUID(),
    element_type: type,
    label: preset?.label ?? type,
    data_key:
      type === 'qr_code' ? 'invite.barcode_payload' :
      undefined,
    x: defaults.x ?? 0.5,
    y: defaults.y ?? 0.5,
    width: defaults.width ?? 0.2,
    height: defaults.height ?? 0.05,
    rotation: defaults.rotation ?? 0,
    font_family: defaults.font_family ?? 'Cairo',
    font_size: defaults.font_size ?? 24,
    font_weight: defaults.font_weight ?? 'normal',
    font_color: defaults.font_color ?? '#111827',
    text_align: defaults.text_align ?? 'center',
    text_direction: defaults.text_direction ?? 'rtl',
    line_height: defaults.line_height ?? 1.2,
    letter_spacing: 0,
    qr_size: defaults.qr_size ?? 0.18,
    qr_color: defaults.qr_color ?? '#000000',
    qr_bg_color: defaults.qr_bg_color ?? '#ffffff',
    qr_error_level: defaults.qr_error_level ?? 'M',
    static_content: defaults.static_content ?? '',
    is_visible: defaults.is_visible ?? true,
    z_index: index,
    sort_order: index,
    slot_index: undefined,
  }
}

/**
 * Find the nearest barcode element by Euclidean distance to the given element.
 * Returns the barcode's slot_index (its order among barcodes), or null if none found.
 */
function findNearestBarcodeSlot(element: EditorElement, allElements: EditorElement[]): number | null {
  const barcodes = allElements.filter(e => e.element_type === 'qr_code' || e.element_type === 'barcode')
  if (barcodes.length === 0) return null

  let nearestIdx = 0
  let nearestDist = Infinity
  barcodes.forEach((bc, idx) => {
    const dx = (element.x + element.width / 2) - (bc.x + bc.width / 2)
    const dy = (element.y + element.height / 2) - (bc.y + bc.height / 2)
    const dist = Math.sqrt(dx * dx + dy * dy)
    if (dist < nearestDist) {
      nearestDist = dist
      nearestIdx = idx
    }
  })
  return nearestIdx
}

function normalizeQrElementBox<T extends Pick<EditorElement, 'element_type' | 'width' | 'height' | 'qr_size'>>(
  element: T,
  canvasWidth: number,
  canvasHeight: number,
  preferredSidePx?: number,
): T {
  if (element.element_type !== 'qr_code') return element
  const sidePx = Math.max(
    24,
    Math.min(
      canvasWidth,
      canvasHeight,
      preferredSidePx ?? element.width * canvasWidth,
    ),
  )
  const width = Math.max(0.02, Math.min(1, sidePx / canvasWidth))
  const height = Math.max(0.02, Math.min(1, sidePx / canvasHeight))
  return { ...element, width, height, qr_size: width }
}

type TabState = {
  templateName: string
  backgroundFile: File | null
  backgroundPreview: string
  backgroundFileKind: BackgroundFileKind
  backgroundTransform: BackgroundTransform
  canvasWidth: number
  canvasHeight: number
  elements: EditorElement[]
  viewTransform: { zoom: number; panX: number; panY: number }
  selectedId: string | null
}

function createFreshTabState(eventTitle: string, ticketClass: 'vip' | 'normal'): TabState {
  const defaultEl = createDefaultElement('qr_code', 0)
  defaultEl.label = 'باركود 1'
  return {
    templateName: `${eventTitle} - ${ticketClass === 'vip' ? 'VIP' : 'عادي'}`,
    backgroundFile: null,
    backgroundPreview: '',
    backgroundFileKind: 'image',
    backgroundTransform: { scale: 1, offsetX: 0, offsetY: 0, fitMode: 'manual' },
    canvasWidth: 1240,
    canvasHeight: 1754,
    elements: [defaultEl],
    viewTransform: { zoom: 1, panX: 0, panY: 0 },
    selectedId: null,
  }
}

const applyFontFaces = (list: { value: string }[]) => {
  let styleEl = document.getElementById('dynamic-font-faces') as HTMLStyleElement
  if (!styleEl) {
    styleEl = document.createElement('style')
    styleEl.id = 'dynamic-font-faces'
    document.head.appendChild(styleEl)
  }

  const rawApiUrl = import.meta.env.VITE_API_URL || '/api/v1'
  const cleanApiUrl = rawApiUrl.endsWith('/') ? rawApiUrl.slice(0, -1) : rawApiUrl
  const apiBase = cleanApiUrl.startsWith('http') 
    ? cleanApiUrl 
    : `${window.location.protocol}//${window.location.host}${cleanApiUrl.startsWith('/') ? cleanApiUrl : '/' + cleanApiUrl}`

  const baseUrl = `${apiBase}/templates/fonts/file`.replace(/([^:]\/)\/+/g, "$1")

  let rules = ''
  list.forEach((item) => {
    // Put bare filename FIRST — custom uploaded fonts won't have -Regular/-Bold suffixes.
    // font-display: swap ensures text is visible immediately while font loads.
    rules += `
      @font-face {
        font-family: '${item.value}';
        src: url('${baseUrl}/${item.value}.ttf') format('truetype'),
             url('${baseUrl}/${item.value}-Regular.ttf') format('truetype'),
             url('${baseUrl}/${item.value}.otf') format('opentype'),
             url('${baseUrl}/${item.value}-Regular.otf') format('opentype');
        font-weight: normal;
        font-style: normal;
        font-display: swap;
      }
      @font-face {
        font-family: '${item.value}';
        src: url('${baseUrl}/${item.value}-Bold.ttf') format('truetype'),
             url('${baseUrl}/${item.value}.ttf') format('truetype'),
             url('${baseUrl}/${item.value}-Bold.otf') format('opentype'),
             url('${baseUrl}/${item.value}.otf') format('opentype');
        font-weight: bold;
        font-style: normal;
        font-display: swap;
      }
    `
  })
  styleEl.innerHTML = rules

  // Actively preload each font using the FontFace API so the browser
  // actually downloads the file *now* instead of waiting until first use.
  list.forEach((item) => {
    const normalUrl = `${baseUrl}/${item.value}.ttf`
    const regularUrl = `${baseUrl}/${item.value}-Regular.ttf`
    const face = new FontFace(
      item.value,
      `url('${normalUrl}'), url('${regularUrl}')`,
      { weight: 'normal', style: 'normal', display: 'swap' },
    )
    face.load().then((loaded) => {
      document.fonts.add(loaded)
    }).catch(() => {
      // Silent — the @font-face CSS will still act as fallback
    })
  })
}

export default function EventDesignEditorPage() {
  const { eventId } = useParams<{ eventId: string }>()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  const editTemplateId = searchParams.get('edit') // If editing existing template
  const currentTenantId = useAuthStore((s) => s.currentTenantId)
  const { data: event, isLoading } = useEventDetail(currentTenantId, eventId)
  const canDesign = usePermission(PERM.TMPL_DESIGN)

  const [excelColumns, setExcelColumns] = useState<string[]>(() => {
    try {
      const saved = sessionStorage.getItem(`excel_cols_${eventId}`)
      return saved ? JSON.parse(saved) : []
    } catch {
      return []
    }
  })
  const [uploadedExcelName, setUploadedExcelName] = useState<string>(() => {
    return sessionStorage.getItem(`excel_name_${eventId}`) || ''
  })
  const [isManualKey, setIsManualKey] = useState(false)

  // All presets are always available to maintain visual symmetry (2x2 grid)
  const availablePresets = ELEMENT_PRESETS

  const [templateName, setTemplateName] = useState(`تصميم مخصص`)
  const [activeTab, setActiveTab] = useState<'vip' | 'normal'>(() => {
    const cls = searchParams.get('class')
    return cls === 'vip' || cls === 'normal' ? cls : 'normal'
  })

  // Dynamic Fonts List & Upload State
  const [fontsList, setFontsList] = useState<{ value: string; label: string }[]>([
    { value: 'Cairo', label: 'Cairo (الافتراضي)' },
    { value: 'Tajawal', label: 'Tajawal (خط تجول)' },
    { value: 'Amiri', label: 'Amiri (الخط الأميري)' },
    { value: 'Noto', label: 'Noto Sans (نوتو)' },
  ])
  const [isUploadingFont, setIsUploadingFont] = useState(false)

  // Load fonts list on mount
  useEffect(() => {
    const fetchFonts = async () => {
      try {
        const list = await templatesApi.listFonts()
        if (list && list.length > 0) {
          const prettyMap: Record<string, string> = {
            'Cairo': 'Cairo (الافتراضي)',
            'Tajawal': 'Tajawal (خط تجول)',
            'Amiri': 'Amiri (الخط الأميري)',
            'Noto': 'Noto Sans (نوتو)',
            'NotoSansArabic': 'Noto Sans (نوتو)',
            'Almarai': 'Almarai (خط المراعي)',
            'Alexandria': 'Alexandria (خط الإسكندرية)',
            'ElMessiri': 'El Messiri (خط المسيري)',
            'ReemKufi': 'Reem Kufi (خط ريم كوفي)',
            'Changa': 'Changa (خط شانغا)'
          }
          const mapped = list.map(item => ({
            value: item.value,
            label: prettyMap[item.value] || `${item.value} (خط مخصص)`
          }))
          setFontsList(mapped)
          applyFontFaces(list)
        }
      } catch (err) {
        console.error('Failed to load dynamic fonts:', err)
      }
    }
    fetchFonts()
  }, [])
  const [pagePreset, setPagePreset] = useState<PagePreset>('Custom')
  const [autoPageMode, setAutoPageMode] = useState<AutoPageMode>('auto')
  const [canvasWidth, setCanvasWidth] = useState(1240)
  const [canvasHeight, setCanvasHeight] = useState(1754)
  const [backgroundFile, setBackgroundFile] = useState<File | null>(null)
  const [backgroundPreview, setBackgroundPreview] = useState('')
  const [backgroundFileKind, setBackgroundFileKind] = useState<BackgroundFileKind>('image')
  const [backgroundTransform, setBackgroundTransform] = useState<BackgroundTransform>({
    scale: 1,
    offsetX: 0,
    offsetY: 0,
    fitMode: 'manual',
  })
  const [viewTransform, setViewTransform] = useState({ zoom: 1, panX: 0, panY: 0 })
  const [qrPreviewSrc, setQrPreviewSrc] = useState('')
  const [qrPreviewVisible, setQrPreviewVisible] = useState(true)
  const [elements, setElements] = useState<EditorElement[]>([createDefaultElement('qr_code', 0)])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [localError, setLocalError] = useState<unknown>(null)
  const [isSaving, setIsSaving] = useState(false)
  const [isUploadingAsset, setIsUploadingAsset] = useState(false)
  const [isSpacePressed, setIsSpacePressed] = useState(false)
  const [previewMode, setPreviewMode] = useState(false)
  const [editingTemplateId, setEditingTemplateId] = useState<string | null>(editTemplateId)
  const [isLoadingTemplate, setIsLoadingTemplate] = useState(!!editTemplateId)
  const [showSaveSuccessModal, setShowSaveSuccessModal] = useState(false)
  const [savedTemplateId, setSavedTemplateId] = useState<string | null>(null)
  const [modalAlert, setModalAlert] = useState<{ title: string; message: string; type: 'success' | 'error' | 'info' } | null>(null)
  const [localImageFiles, setLocalImageFiles] = useState<Record<string, File>>({})
  void localImageFiles

  // Per-tab snapshots to preserve state when switching
  const tabSnapshots = useRef<Record<'vip' | 'normal', TabState | null>>({ vip: null, normal: null })
  
  const viewportRef = useRef<HTMLDivElement | null>(null)
  const viewportPanRef = useRef<null | { startClientX: number; startClientY: number; startPanX: number; startPanY: number }>(null)
  const dragRef = useRef<
    | {
        id: string
        mode: 'move' | 'resize'
        offsetX: number
        offsetY: number
        startClientX: number
        startClientY: number
        startWorldX: number
        startWorldY: number
        startX: number
        startY: number
        startWidth: number
        startHeight: number
        startFontSize: number
      }
    | null
  >(null)

  useEffect(() => {
    if (event) {
        setTemplateName(`${event.title} - ${activeTab === 'vip' ? 'VIP' : 'عادي'}`)
    }
  }, [activeTab, event])

  // ── Load existing template for editing ──
  useEffect(() => {
    if (!editTemplateId) return
    let cancelled = false

    const loadTemplate = async () => {
      try {
        setIsLoadingTemplate(true)
        // Load template metadata
        const res = await import('@services/http/client').then(m => m.default)
        const { data: tpl } = await res.get(`/templates/${editTemplateId}`)
        if (cancelled) return

        // Set template properties
        setTemplateName(tpl.name || 'تصميم مخصص')
        if (tpl.width_px) setCanvasWidth(tpl.width_px)
        if (tpl.height_px) setCanvasHeight(tpl.height_px)
        if (tpl.ticket_class === 'vip') setActiveTab('vip')
        if (tpl.background_url) setBackgroundPreview(tpl.background_url)
        if (tpl.metadata?.background_transform) {
          setBackgroundTransform(tpl.metadata.background_transform)
        }

        // Load elements
        const { data: elems } = await res.get(`/templates/${editTemplateId}/elements`)
        if (cancelled) return

        if (elems && elems.length > 0) {

          const mapped: EditorElement[] = elems.map((e: any, i: number) => ({
            id: e.id || `elem-${i}-${Date.now()}`,
            element_type: e.element_type,
            label: e.label || e.element_type,
            data_key: e.data_key || null,
            x: e.x ?? 0.1,
            y: e.y ?? 0.1,
            width: e.width ?? 0.2,
            height: e.height ?? 0.1,
            rotation: e.rotation ?? 0,
            font_family: e.font_family || 'Cairo',
            font_size: e.font_size ?? 20,
            font_weight: e.font_weight || 'normal',
            font_color: e.font_color || '#374151',
            text_align: e.text_align || 'center',
            text_direction: e.text_direction || 'rtl',
            line_height: e.line_height ?? 1.4,
            letter_spacing: 0,
            qr_size: e.qr_size ?? 200,
            qr_color: e.qr_color || '#000000',
            qr_bg_color: e.qr_bg_color || '#FFFFFF',
            qr_error_level: e.qr_error_level || 'M',
            static_content: e.static_content || '',
            is_visible: e.is_visible ?? true,
            z_index: e.z_index ?? i,
            sort_order: e.sort_order ?? i,
            slot_index: e.slot_index,
          }))
          setElements(mapped)
        }

        setEditingTemplateId(editTemplateId)
      } catch (err) {
        console.error('Failed to load template:', err)
        setLocalError('فشل تحميل القالب للتحرير')
      } finally {
        if (!cancelled) setIsLoadingTemplate(false)
      }
    }

    loadTemplate()
    return () => { cancelled = true }
  }, [editTemplateId])

  const switchTab = (target: 'vip' | 'normal') => {
    if (target === activeTab) return

    // Save current tab state
    tabSnapshots.current[activeTab] = {
      templateName,
      backgroundFile,
      backgroundPreview,
      backgroundFileKind,
      backgroundTransform,
      canvasWidth,
      canvasHeight,
      elements,
      viewTransform,
      selectedId,
    }

    // Restore or create fresh state for target tab
    const saved = tabSnapshots.current[target]
    if (saved) {
      setTemplateName(saved.templateName)
      setBackgroundFile(saved.backgroundFile)
      setBackgroundPreview(saved.backgroundPreview)
      setBackgroundFileKind(saved.backgroundFileKind)
      setBackgroundTransform(saved.backgroundTransform)
      setCanvasWidth(saved.canvasWidth)
      setCanvasHeight(saved.canvasHeight)
      setElements(saved.elements)
      setViewTransform(saved.viewTransform)
      setSelectedId(saved.selectedId)
    } else {
      const fresh = createFreshTabState(event?.title ?? 'تصميم', target)
      setTemplateName(fresh.templateName)
      setBackgroundFile(null)
      setBackgroundPreview('')
      setBackgroundFileKind('image')
      setBackgroundTransform(fresh.backgroundTransform)
      setCanvasWidth(fresh.canvasWidth)
      setCanvasHeight(fresh.canvasHeight)
      setElements(fresh.elements)
      setViewTransform(fresh.viewTransform)
      setSelectedId(null)
    }

    setLocalError(null)
    setActiveTab(target)
  }

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.code === 'Space' && document.activeElement?.tagName !== 'INPUT' && document.activeElement?.tagName !== 'TEXTAREA') {
        e.preventDefault()
        setIsSpacePressed(true)
      }
    }
    const handleKeyUp = (e: KeyboardEvent) => {
      if (e.code === 'Space') {
        setIsSpacePressed(false)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    window.addEventListener('keyup', handleKeyUp)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      window.removeEventListener('keyup', handleKeyUp)
    }
  }, [])

  useEffect(() => {
    if (!backgroundFile) {
      setBackgroundPreview('')
      return
    }

    const url = URL.createObjectURL(backgroundFile)
    const isPdf = backgroundFile.type === 'application/pdf'
    setBackgroundFileKind(isPdf ? 'pdf' : 'image')
    
    // Add parameters to hide PDF viewer UI and fit width/height
    setBackgroundPreview(isPdf ? `${url}#toolbar=0&navpanes=0&scrollbar=0&view=Fit` : url)
    
    return () => URL.revokeObjectURL(url)
  }, [backgroundFile])

  useEffect(() => {
    if (!eventId) return

    const payload = `QENTRY-${eventId.slice(0, 8).toUpperCase()}-${Math.floor(100000 + Math.random() * 900000)}`

    let cancelled = false
    QRCode.toDataURL(payload, {
      errorCorrectionLevel: 'M',
      margin: 1,
      width: 640,
      color: {
        dark: '#111827',
        light: '#FFFFFF',
      },
    })
      .then((url: string) => {
        if (!cancelled) setQrPreviewSrc(url)
      })
      .catch(() => {
        if (!cancelled) setQrPreviewSrc('')
      })

    return () => {
      cancelled = true
    }
  }, [eventId])

  const autoFitCanvas = (width: number, height: number) => {
    if (!viewportRef.current) return
    const rect = viewportRef.current.getBoundingClientRect()
    const padding = 60
    const scaleX = (rect.width - padding) / width
    const scaleY = (rect.height - padding) / height
    const fitZoom = Math.min(scaleX, scaleY, 1)
    
    const panX = (rect.width - width * fitZoom) / 2
    const panY = (rect.height - height * fitZoom) / 2

    setViewTransform({ zoom: Number(fitZoom.toFixed(2)), panX, panY })
  }

  const applyBackgroundDimensions = async (file: File) => {
    try {
      const info = await templatesApi.inspectBackground(file)
      setCanvasWidth(info.width_px)
      setCanvasHeight(info.height_px)
      setPagePreset('Custom')
      setAutoPageMode('auto')
      if (info.preview_data_url) {
        if (backgroundPreview.startsWith('blob:')) {
          URL.revokeObjectURL(backgroundPreview)
        }
        setBackgroundPreview(info.preview_data_url)
        setBackgroundFileKind('image')
      }
      setLocalError(null)
      autoFitCanvas(info.width_px, info.height_px)
    } catch (error: any) {
      setLocalError(error)
    }
  }

  const selectedElement = useMemo(
    () => elements.find((item) => item.id === selectedId) ?? null,
    [elements, selectedId],
  )

  const backgroundStyle = useMemo(() => {
    if (!backgroundPreview) return undefined
    return {
      transform: `translate(${backgroundTransform.offsetX}px, ${backgroundTransform.offsetY}px) scale(${backgroundTransform.scale})`,
      transformOrigin: 'center center',
    }
  }, [backgroundPreview, backgroundTransform])

  // (Removed global body scroll lock to allow scrolling outside the viewport)

  // Native non-passive wheel handler to reliably prevent page scroll
  useEffect(() => {
    const el = viewportRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      e.stopPropagation()
      const viewportBox = el.getBoundingClientRect()
      const pointerX = e.clientX - viewportBox.left
      const pointerY = e.clientY - viewportBox.top
      const delta = e.deltaY > 0 ? -0.12 : 0.12
      setViewTransform((prev) => {
        const nextZoom = Math.min(2.8, Math.max(0.45, Number((prev.zoom + delta).toFixed(2))))
        const worldX = (pointerX - prev.panX) / prev.zoom
        const worldY = (pointerY - prev.panY) / prev.zoom
        return {
          zoom: nextZoom,
          panX: pointerX - worldX * nextZoom,
          panY: pointerY - worldY * nextZoom,
        }
      })
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  })



  const handleCanvasMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!isSpacePressed) {
      const target = e.target as HTMLElement
      const isBackgroundHit = target.classList.contains('inv-design-canvas__bg') || target.classList.contains('inv-design-canvas__bg--empty')
      if (e.target !== e.currentTarget && !isBackgroundHit) return
    }
    e.preventDefault()
    viewportPanRef.current = {
      startClientX: e.clientX,
      startClientY: e.clientY,
      startPanX: viewTransform.panX,
      startPanY: viewTransform.panY,
    }
  }

  const handleBackgroundChange = async (file: File | null) => {
    if (!file) {
      setBackgroundFile(null)
      return
    }
    if (backgroundPreview.startsWith('blob:')) {
      URL.revokeObjectURL(backgroundPreview)
    }
    const objectUrl = URL.createObjectURL(file)
    setBackgroundFile(file)
    setBackgroundFileKind(file.type === 'application/pdf' ? 'pdf' : 'image')
    setBackgroundPreview(objectUrl)
    setBackgroundTransform({ scale: 1, offsetX: 0, offsetY: 0, fitMode: 'manual' })
    
    try {
      const tmplId = await ensureTemplateId()
      await templatesApi.uploadBackground(tmplId, file)
      await applyBackgroundDimensions(file)
    } catch (err: any) {
      setLocalError(err)
    }
  }

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (viewportPanRef.current) {
        const deltaX = e.clientX - viewportPanRef.current.startClientX
        const deltaY = e.clientY - viewportPanRef.current.startClientY
        setViewTransform({
          zoom: viewTransform.zoom,
          panX: viewportPanRef.current.startPanX + deltaX,
          panY: viewportPanRef.current.startPanY + deltaY,
        })
        return
      }

      const drag = dragRef.current
      if (!drag || !viewportRef.current) return
      const viewportBox = viewportRef.current?.getBoundingClientRect()
      if (!viewportBox) return
      const target = elements.find((item) => item.id === drag.id)
      if (!target) return

      const clientX = (Math.min(Math.max(e.clientX, viewportBox.left), viewportBox.right) - viewportBox.left - viewTransform.panX) / viewTransform.zoom
      const clientY = (Math.min(Math.max(e.clientY, viewportBox.top), viewportBox.bottom) - viewportBox.top - viewTransform.panY) / viewTransform.zoom
      if (drag.mode === 'move') {
        const nextX = (clientX - drag.offsetX) / canvasWidth
        const nextY = (clientY - drag.offsetY) / canvasHeight

        setElements((prev) => prev.map((item) => item.id === target.id ? {
          ...item,
          x: Math.min(1.0 - item.width, Math.max(0.0, nextX)),
          y: Math.min(1.0 - item.height, Math.max(0.0, nextY)),
        } : item))
        return
      }

      const deltaWorldX = clientX - drag.startWorldX
      const deltaWorldY = clientY - drag.startWorldY
      const targetIsQrCode = target.element_type === 'qr_code'
      const targetIsImage = target.element_type === 'image'
      const nextWidthPx = drag.startWidth + deltaWorldX
      const nextHeightPx = drag.startHeight + deltaWorldY
      const nextSidePx = Math.max(40, Math.max(nextWidthPx, nextHeightPx))

      // Scale font size proportionally with element size
      const widthRatio = Math.max(nextWidthPx, 30) / drag.startWidth
      const heightRatio = Math.max(nextHeightPx, 20) / drag.startHeight
      const sizeRatio = (widthRatio + heightRatio) / 2
      const scaledFontSize = (!targetIsQrCode && !targetIsImage)
        ? Math.round(Math.max(8, Math.min(120, drag.startFontSize * sizeRatio)))
        : undefined

      setElements((prev) => prev.map((item) => {
        if (item.id !== target.id) return item
        
        let w = nextWidthPx
        let h = nextHeightPx
        if (targetIsImage) {
          const startRatio = drag.startWidth / drag.startHeight
          w = Math.max(20, nextWidthPx)
          h = w / startRatio
        }
        
        return {
          ...item,
          width: targetIsQrCode
            ? Math.min(1.0, Math.max(0.05, nextSidePx / canvasWidth))
            : Math.min(1.0, Math.max(0.05, w / canvasWidth)),
          height: targetIsQrCode
            ? Math.min(1.0, Math.max(0.05, nextSidePx / canvasHeight))
            : Math.min(1.0, Math.max(0.05, h / canvasHeight)),
          ...(scaledFontSize !== undefined ? { font_size: scaledFontSize } : {}),
        }
      }))
    }

    const handleMouseUp = () => {
      dragRef.current = null
      viewportPanRef.current = null
    }

    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [canvasHeight, canvasWidth, elements, viewTransform.panX, viewTransform.panY, viewTransform.zoom])

  const addElement = (type: TemplateElementType) => {

    const next = createDefaultElement(type, elements.length)
    const preset = ELEMENT_PRESETS.find((p) => p.type === type)
    const typeCount = elements.filter((e) => e.element_type === type).length
    next.label = `${preset?.label ?? type} ${typeCount + 1}`

    // Auto-assign slot_index for dynamic text elements (link to nearest barcode)
    const isDynamic = type === 'dynamic_text' || type === 'guest_name'
    if (isDynamic) {
      const barcodes = elements.filter(e => e.element_type === 'qr_code' || e.element_type === 'barcode')
      if (barcodes.length > 0) {
        // Find nearest barcode by proximity
        const slot = findNearestBarcodeSlot(next, elements)
        next.slot_index = slot ?? undefined
      }
    }

    setElements((prev) => [...prev, next])
    setSelectedId(next.id)
  }

  const deleteElementById = (id: string) => {
    setElements((prev) => prev.filter((item) => item.id !== id))
    if (selectedId === id) setSelectedId(null)
  }

  const updateElementById = (id: string, patch: Partial<EditorElement>) => {
    setElements((prev) => prev.map((item) => {
      if (item.id !== id) return item
      if (item.element_type !== 'qr_code') return { ...item, ...patch }

      const hasWidth = typeof patch.width === 'number'
      const hasHeight = typeof patch.height === 'number'
      if (!hasWidth && !hasHeight) return { ...item, ...patch }

      const sidePx = hasWidth
        ? (patch.width ?? item.width) * canvasWidth
        : (patch.height ?? item.height) * canvasHeight
      return normalizeQrElementBox({ ...item, ...patch }, canvasWidth, canvasHeight, sidePx)
    }))
  }

  const updateSelected = (patch: Partial<EditorElement>) => {
    if (!selectedElement) return
    updateElementById(selectedElement.id, patch)
  }

  const handleFontUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    
    setIsUploadingFont(true)
    try {
      const res = await templatesApi.uploadFont(file)
      if (res.status === 'success') {
        const list = await templatesApi.listFonts()
        const prettyMap: Record<string, string> = {
          'Cairo': 'Cairo (الافتراضي)',
          'Tajawal': 'Tajawal (خط تجول)',
          'Amiri': 'Amiri (الخط الأميري)',
          'Noto': 'Noto Sans (نوتو)',
          'NotoSansArabic': 'Noto Sans (نوتو)',
          'Almarai': 'Almarai (خط المراعي)',
          'Alexandria': 'Alexandria (خط الإسكندرية)',
          'ElMessiri': 'El Messiri (خط المسيري)',
          'ReemKufi': 'Reem Kufi (خط ريم كوفي)',
          'Changa': 'Changa (خط شانغا)'
        }
        const mapped = list.map(item => ({
          value: item.value,
          label: prettyMap[item.value] || `${item.value} (خط مخصص)`
        }))
        setFontsList(mapped)
        applyFontFaces(list)
        
        // Wait for the uploaded font to be ready before applying it
        // This prevents the race condition where font_family is set
        // but the font file hasn't been downloaded yet by the browser.
        const fontFamily = res.font_family
        try {
          await document.fonts.ready
          // Give the browser a brief moment to register the newly loaded font
          await new Promise(resolve => setTimeout(resolve, 200))
        } catch {
          // Proceed anyway — applyFontFaces CSS rules will eventually load it
        }
        
        // Auto-select the uploaded font for active element
        updateSelected({ font_family: fontFamily })
        setModalAlert({
          title: 'نجاح تفعيل الخط',
          message: `تم رفع وتفعيل الخط بنجاح: ${fontFamily}`,
          type: 'success'
        })
      }
    } catch (err: any) {
      console.error('Failed to upload font:', err)
      const errorMsg = getApiErrorMessage(err, 'فشل رفع ملف الخط. تأكد أنه ملف .ttf أو .otf صالح.')
      setModalAlert({
        title: 'فشل رفع الخط',
        message: errorMsg,
        type: 'error'
      })
    } finally {
      setIsUploadingFont(false)
      e.target.value = ''
    }
  }

  const deleteSelected = () => {
    if (!selectedElement) return
    setElements((prev) => prev.filter((item) => item.id !== selectedElement.id))
    setSelectedId(null)
  }

  const duplicateSelected = () => {
    if (!selectedElement) return
    const duplicate: EditorElement = {
      ...selectedElement,
      id: generateUUID(),
      x: Math.min(0.9, selectedElement.x + 0.04),
      y: Math.min(0.9, selectedElement.y + 0.04),
      z_index: (selectedElement.z_index ?? 0) + 1,
      sort_order: (selectedElement.sort_order ?? 0) + 1,
    }
    setElements((prev) => [...prev, duplicate])
    setSelectedId(duplicate.id)
  }

  const ensureTemplateId = async (): Promise<string> => {
    if (editingTemplateId) return editingTemplateId

    const tmpl = await templatesApi.create({
      event_id: event!.id,
      name: templateName.trim() || `${event!.title} - ${activeTab === 'vip' ? 'VIP' : 'عادي'}`,
      template_type: 'designed',
      ticket_class: activeTab,
      width_px: canvasWidth,
      height_px: canvasHeight,
      orientation: 'portrait',
      background_color: '#ffffff',
      metadata: {
        source: 'event-design-editor',
        page_mode: autoPageMode,
        page_preset: pagePreset,
        background_transform: backgroundTransform,
      },
    })
    
    setEditingTemplateId(tmpl.id)
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set('edit', tmpl.id)
      return next
    })
    return tmpl.id
  }

  const saveOneTab = async (
    _tc: 'vip' | 'normal',
    tName: string,
    bgFile: File | null,
    els: EditorElement[],
    cw: number,
    ch: number,
    bgTransform: BackgroundTransform,
    _existingTemplateId?: string | null,
  ) => {
    const tmplId = await ensureTemplateId()

    // Update existing template fields
    await import('@services/http/client').then(async (m) => {
      await m.default.patch(`/templates/${tmplId}`, {
        name: tName.trim(),
        width_px: cw,
        height_px: ch,
        metadata: {
          source: 'event-design-editor',
          page_mode: autoPageMode,
          page_preset: pagePreset,
          background_transform: bgTransform,
        },
      })
    })

    if (bgFile) {
      await templatesApi.uploadBackground(tmplId, bgFile)
    }

    const finalElements = els.map((element) => {
      const { id: _id, ...rest } = element
      if (rest.element_type !== 'qr_code') return rest
      return normalizeQrElementBox(rest, cw, ch)
    })

    const savedElements = await templatesApi.replaceElements(tmplId, finalElements)
    return { tmplId, savedElements }
  }

  const downloadCustomExcelTemplate = async () => {
    // Gather custom fields from elements
    const customKeys = new Set<string>()
    elements.forEach((el) => {
      if (el.element_type === 'dynamic_text' || el.element_type === 'guest_name') {
        if (el.data_key && el.data_key.trim()) {
          const dk = el.data_key.trim()
          // Exclude guest name and standard columns that match our base three
          if (!['اسم الضيف', 'guest_name', 'name', 'guest.name', 'عدد الدعوات', 'عدد الأشخاص', 'invitation_count', 'count', 'نوع التذكرة', 'ticket_class', 'class'].includes(dk)) {
            customKeys.add(dk)
          }
        }
      }
    })

    // Base columns
    const baseHeaders = ['اسم الضيف', 'عدد الدعوات', 'نوع التذكرة']
    const allHeaders = [...baseHeaders, ...Array.from(customKeys)]

    // Create dummy row data
    const dummyRow: Record<string, unknown> = {
      'اسم الضيف': 'محمد عبدالله العمري',
      'عدد الدعوات': 1,
      'نوع التذكرة': activeTab === 'vip' ? 'VIP' : 'normal'
    }
    customKeys.forEach((key) => {
      dummyRow[key] = `بيانات ${key}`
    })

    const guideRows = [
      { 'العمود': 'اسم الضيف', 'النوع': 'نص (إلزامي)', 'الوصف': 'الاسم الكامل للضيف المطبوع على البطاقة' },
      { 'العمود': 'عدد الدعوات', 'النوع': 'رقم (اختياري)', 'الوصف': 'عدد البطاقات المطلوب توليدها لهذا الضيف (الافتراضي 1)' },
      { 'العمود': 'نوع التذكرة', 'النوع': 'VIP أو normal (اختياري)', 'الوصف': 'فئة التذكرة الخاصة بالضيف (VIP أو عادي)' },
    ]
    customKeys.forEach((key) => {
      guideRows.push({
        'العمود': key,
        'النوع': 'نص (حسب التصميم)',
        'الوصف': `الحقل المخصص المربوط بـ "${key}" في التصميم الخاص بك`
      })
    })
    await downloadSpreadsheet([
      { name: 'المدعوين', rows: [dummyRow], headers: allHeaders },
      { name: 'دليل تعبئة الحقول', rows: guideRows },
    ], `نموذج_دعوات_${templateName.replace(/\s+/g, '_')}.xlsx`)
  }

  const handleSave = async () => {
    if (!event) return
    if (!templateName.trim()) {
      setLocalError('اكتب اسمًا للقالب أولاً')
      return
    }
    if (!backgroundFile && !backgroundPreview) {
      setLocalError('ارفع تصميم الخلفية أولاً')
      return
    }

    // Save current tab snapshot
    tabSnapshots.current[activeTab] = {
      templateName, backgroundFile, backgroundPreview, backgroundFileKind,
      backgroundTransform, canvasWidth, canvasHeight, elements, viewTransform, selectedId,
    }

    setIsSaving(true)
    setLocalError(null)
    try {
      const { tmplId, savedElements } = await saveOneTab(
        activeTab,
        templateName,
        backgroundFile,
        elements,
        canvasWidth,
        canvasHeight,
        backgroundTransform,
        editingTemplateId,
      )

      // Update state so we don't have stale/blob URLs and old IDs
      setEditingTemplateId(tmplId)
      setElements(savedElements.map((e, i) => ({
        id: e.id,
        element_type: e.element_type,
        label: e.label || e.element_type,
        data_key: e.data_key || null,
        x: Number(e.x),
        y: Number(e.y),
        width: Number(e.width),
        height: Number(e.height),
        rotation: Number(e.rotation ?? 0),
        font_family: e.font_family || 'Cairo',
        font_size: e.font_size ?? 20,
        font_weight: e.font_weight || 'normal',
        font_color: e.font_color || '#374151',
        text_align: e.text_align || 'center',
        text_direction: e.text_direction || 'rtl',
        line_height: e.line_height ?? 1.4,
        letter_spacing: 0,
        qr_size: e.qr_size ?? 200,
        qr_color: e.qr_color || '#000000',
        qr_bg_color: e.qr_bg_color || '#FFFFFF',
        qr_error_level: e.qr_error_level || 'M',
        static_content: e.static_content || '',
        is_visible: e.is_visible ?? true,
        z_index: e.z_index ?? i,
        sort_order: e.sort_order ?? i,
        slot_index: e.slot_index,
      })))

      // Clear the uploaded files cache since they are now stored on the server
      setLocalImageFiles({})

      // Update search params in URL so reload maintains the edit state
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev)
        next.set('edit', tmplId)
        return next
      })

      setSavedTemplateId(tmplId)
      setShowSaveSuccessModal(true)
      setIsSaving(false)
    } catch (err: any) {
      setLocalError(err)
      setIsSaving(false)
    }
  }

  if (isLoading || isLoadingTemplate) {
    return (
      <WorkspaceShell title="جاري التحميل…" subtitle="">
        <div className="center-loader" style={{ paddingTop: 80 }}>
          <Loader2 size={36} className="spin" />
          <span>{isLoadingTemplate ? 'جاري تحميل القالب للتحرير…' : 'جاري تحميل المحرر…'}</span>
        </div>
      </WorkspaceShell>
    )
  }

  if (!event) {
     return (
        <WorkspaceShell title="خطأ" subtitle="">
            <div className="center-loader">
                الحدث غير موجود
            </div>
        </WorkspaceShell>
     )
  }

  if (!canDesign) {
    return (
      <WorkspaceShell title="غير مصرح" subtitle="">
        <div className="center-loader">
          ليس لديك صلاحية لاستخدام محرر التصميم. تواصل مع مسؤول المؤسسة.
        </div>
      </WorkspaceShell>
    )
  }

  return (
    <WorkspaceShell
      title={editingTemplateId ? 'تحرير التصميم' : 'محرر تصميم الدعوات'}
      subtitle={event?.title ? `حدث: ${event.title}` : ''}
      hideSidebar
      actions={
        <div className="header-actions">
            <button className="btn btn-ghost" onClick={() => navigate(editingTemplateId ? `/events/${event.id}?tab=templates` : `/events/${event.id}?tab=invitations&source=design`)} disabled={isSaving || isUploadingAsset}>
                <ArrowRight size={16} style={{ marginLeft: 6 }} />
                {editingTemplateId ? 'إلغاء والعودة' : 'إلغاء والعودة'}
            </button>
            <Can permission={PERM.TMPL_DESIGN}>
              <button className="btn btn-primary" onClick={handleSave} disabled={isSaving || isUploadingAsset}>
                  <Save size={16} />
                  {isSaving ? 'جاري الحفظ...' : isUploadingAsset ? 'جاري رفع الشعار...' : editingTemplateId ? 'حفظ التعديلات' : 'حفظ التصميم'}
              </button>
            </Can>
        </div>
      }
    >
      <div className="inv-design-grid">
        <aside className="inv-design-sidebar-left">
          <div className="inv-design-class-tabs">
            <button
              type="button"
              className={`inv-design-class-tab ${activeTab === 'normal' ? 'inv-design-class-tab--active' : ''}`}
              onClick={() => switchTab('normal')}
              disabled={isSaving}
            >
              عادي
            </button>
            <button
              type="button"
              className={`inv-design-class-tab inv-design-class-tab--vip ${activeTab === 'vip' ? 'inv-design-class-tab--active' : ''}`}
              onClick={() => switchTab('vip')}
              disabled={isSaving}
            >
              ⭐ VIP
            </button>
          </div>

          <label className="inv-label">اسم القالب</label>
          <input
            className="inv-input"
            value={templateName}
            onChange={(e) => setTemplateName(e.target.value)}
            disabled={isSaving}
          />



          <label className="inv-label" style={{ marginTop: 16 }}>🎨 خلفية التصميم</label>
          <label className="inv-upload-btn inv-design-upload">
            <Upload size={15} /> رفع صورة أو PDF للتصميم
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp,application/pdf"
              hidden
              onChange={(e) => void handleBackgroundChange(e.target.files?.[0] ?? null)}
              disabled={isSaving}
            />
          </label>
          {(backgroundPreview || backgroundFile) && (
            <div className="inv-design-preview-note">
              {backgroundFile?.name || 'تم تجهيز معاينة الخلفية'}
            </div>
          )}

          <label className="inv-label" style={{ marginTop: 16 }}>📂 استيراد أعمدة الإكسل (لتسهيل الربط)</label>
          <label className="inv-upload-btn inv-design-upload" style={{ background: 'rgba(16, 185, 129, 0.08)', color: '#34d399', borderColor: 'rgba(16, 185, 129, 0.2)' }}>
            <Upload size={15} /> {uploadedExcelName ? `تغيير ملف الأعمدة: ${uploadedExcelName}` : 'تحميل أسماء الأعمدة من ملف Excel'}
            <input
              type="file"
              accept=".xlsx,.csv"
              hidden
              onChange={async (e) => {
                const file = e.target.files?.[0]
                if (!file) return
                try {
                  const cols = await readSpreadsheetHeaders(file)
                  if (cols.length > 0) {
                    setExcelColumns(cols)
                    setUploadedExcelName(file.name)
                    setIsManualKey(false)
                    sessionStorage.setItem(`excel_cols_${eventId}`, JSON.stringify(cols))
                    sessionStorage.setItem(`excel_name_${eventId}`, file.name)
                    setModalAlert({
                      title: 'تم قراءة الملف بنجاح',
                      message: `تم قراءة ${cols.length} أعمدة بنجاح من ملف ${file.name}${elements.some(e => e.element_type === 'dynamic_text' || e.element_type === 'guest_name') ? ' - يمكنك الآن تحميل نموذج الربط' : ''}`,
                      type: 'success'
                    })
                  } else {
                    setModalAlert({
                      title: 'ملف فارغ',
                      message: 'ملف Excel فارغ أو لا يحتوي على صفوف بيانات',
                      type: 'error'
                    })
                  }
                } catch {
                  setModalAlert({
                    title: 'خطأ في قراءة الملف',
                    message: 'تعذر قراءة الملف. استخدم ملف XLSX أو CSV صالحًا ضمن الحد المسموح.',
                    type: 'error'
                  })
                }
              }}
              disabled={isSaving}
            />
          </label>
          {uploadedExcelName && (
            <div className="inv-design-preview-note" style={{ color: '#34d399', background: 'rgba(16, 185, 129, 0.04)', borderColor: 'rgba(16, 185, 129, 0.18)', borderStyle: 'dashed', borderWidth: '1px', marginTop: '8px' }}>
              ✓ تم تحميل {excelColumns.length} أعمدة من: {uploadedExcelName}
            </div>
          )}



          <label className="inv-label" style={{ marginTop: 16 }}>➕ إضافة عنصر جديد للبطاقة</label>
          <div className="inv-design-toolbar" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '8px' }}>
            {(availablePresets || []).map((preset) => {
              const Icon = preset.icon
              return (
                <button
                  key={preset.type}
                  type="button"
                  className="inv-design-tool"
                  onClick={() => addElement(preset.type)}
                  disabled={isSaving}
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: '6px',
                    padding: '12px 6px',
                    height: 'auto',
                    borderRadius: '10px',
                    textAlign: 'center',
                    fontSize: '11px',
                    fontWeight: 600,
                  }}
                >
                  <Icon size={16} />
                  <span>{preset.label}</span>
                </button>
              )
            })}
          </div>



          <div className="inv-design-layers">
            <div className="inv-design-layers__head">
              <strong>العناصر المضافة على البطاقة</strong>
            </div>
            <div className="inv-design-layers__list">
              {(elements || []).map((el) => (
                <div 
                  key={el.id} 
                  className={`inv-design-layer-item ${selectedId === el.id ? 'inv-design-layer-item--active' : ''}`}
                  onClick={() => setSelectedId(el.id)}
                >
                  {(() => {
                    const p = ELEMENT_PRESETS.find(p => p.type === el.element_type);
                    let Icon = p?.icon;
                    if (!Icon) {
                      if (el.element_type === 'guest_name') Icon = Type;
                      else if (el.element_type === 'barcode') Icon = Barcode;
                      else Icon = Move;
                    }
                    return <Icon size={14} />;
                  })()}
                  <div className="inv-design-layer-item__info">
                    <span>{el.label || 'عنصر بدون اسم'}</span>
                    {(el.element_type === 'dynamic_text' || el.element_type === 'guest_name') && el.data_key && (
                      <span className="inv-design-layer-item__key">{el.data_key}</span>
                    )}
                    {(el.element_type === 'dynamic_text' || el.element_type === 'guest_name') && el.slot_index != null && (
                      <span style={{ fontSize: 9, background: 'rgba(99,102,241,0.2)', color: '#818cf8', padding: '1px 5px', borderRadius: 4, marginRight: 4 }}>
                        Slot {el.slot_index}
                      </span>
                    )}
                  </div>
                  <button type="button" onClick={(e) => { e.stopPropagation(); deleteElementById(el.id) }} title="حذف العنصر">
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
              {elements.length === 0 && (
                <div style={{ textAlign: 'center', color: 'var(--color-text-muted)', fontSize: 12, padding: '10px 0' }}>
                  لا توجد عناصر مضافة بعد
                </div>
              )}
            </div>
          </div>

        </aside>

        <section className="inv-design-canvas-shell">
          <div className="inv-design-toolbar-top">
            <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>{canvasWidth} × {canvasHeight}px</span>
            <div className="inv-design-zoom-controls">
              <button type="button" onClick={() => setViewTransform(p => ({ ...p, zoom: Math.max(0.2, p.zoom - 0.1) }))}>-</button>
              <span>{Math.round(viewTransform.zoom * 100)}%</span>
              <button type="button" onClick={() => setViewTransform(p => ({ ...p, zoom: Math.min(3, p.zoom + 0.1) }))}>+</button>
              <button type="button" onClick={() => autoFitCanvas(canvasWidth, canvasHeight)} style={{ fontSize: 10, width: 'auto', padding: '0 8px' }}>توسيط</button>
              <button
                type="button"
                onClick={() => setPreviewMode(p => !p)}
                style={{
                  fontSize: 10, width: 'auto', padding: '0 10px',
                  background: previewMode ? 'rgba(59,130,246,0.2)' : undefined,
                  color: previewMode ? '#60a5fa' : undefined,
                }}
              >
                <Eye size={12} style={{ marginLeft: 4 }} />
                {previewMode ? 'إيقاف المعاينة' : 'معاينة'}
              </button>
            </div>
          </div>
          <div 
            className="inv-design-canvas" 
            ref={viewportRef} 
            style={{ cursor: isSpacePressed ? 'grab' : 'default' }}
          >
            <div
              className="inv-design-canvas__stage"
              style={{
                width: canvasWidth,
                height: canvasHeight,
                transform: `translate(${viewTransform.panX}px, ${viewTransform.panY}px) scale(${viewTransform.zoom})`,
              }}
              onMouseDown={handleCanvasMouseDown}
            >
              {backgroundPreview ? (
                backgroundFileKind === 'pdf' ? (
                  <iframe className="inv-design-canvas__bg" src={backgroundPreview} title="Background preview" style={backgroundStyle} />
                ) : (
                  <img className="inv-design-canvas__bg" src={backgroundPreview} alt="Background preview" style={backgroundStyle} />
                )
              ) : (
                <div className="inv-design-canvas__bg inv-design-canvas__bg--empty">ارفع الخلفية لرؤية المعاينة هنا</div>
              )}

              {(elements || []).map((element) => {
              const isSelected = element.id === selectedId
              const isQrCode = element.element_type === 'qr_code'
              const isImage = element.element_type === 'image'
              const showQrPreview = isQrCode && qrPreviewVisible
              return (
                <button
                  key={element.id}
                  type="button"
                  draggable={false}
                  className={`inv-design-element ${isQrCode ? 'inv-design-element--barcode' : isImage ? 'inv-design-element--image' : 'inv-design-element--text'} ${isSelected && !previewMode ? 'inv-design-element--selected' : ''}`}
                  style={{
                    left: `${element.x * 100}%`,
                    top: `${element.y * 100}%`,
                    width: `${element.width * 100}%`,
                    height: (isQrCode || isImage) ? `${element.height * 100}%` : 'auto',
                    pointerEvents: previewMode ? 'none' : undefined,
                  }}
                  onMouseDown={(e) => {
                    e.preventDefault()
                    e.stopPropagation()
                    const viewportBox = viewportRef.current?.getBoundingClientRect()
                    if (!viewportBox) return
                    const worldX = (e.clientX - viewportBox.left - viewTransform.panX) / viewTransform.zoom
                    const worldY = (e.clientY - viewportBox.top - viewTransform.panY) / viewTransform.zoom
                    dragRef.current = {
                      id: element.id,
                      mode: 'move',
                      offsetX: worldX - element.x * canvasWidth,
                      offsetY: worldY - element.y * canvasHeight,
                      startClientX: e.clientX,
                      startClientY: e.clientY,
                      startWorldX: worldX,
                      startWorldY: worldY,
                      startX: element.x * canvasWidth,
                      startY: element.y * canvasHeight,
                      startWidth: element.width * canvasWidth,
                      startHeight: element.height * canvasHeight,
                      startFontSize: element.font_size ?? 20,
                    }
                    setSelectedId(element.id)
                  }}
                  onDragStart={(e) => e.preventDefault()}
                  onClick={() => setSelectedId(element.id)}
                >
                  {isQrCode ? (
                    <>
                      <span className={`inv-design-element__barcode-square ${showQrPreview ? 'inv-design-element__barcode-square--visible' : 'inv-design-element__barcode-square--hidden'}`} aria-hidden="true">
                        {showQrPreview && qrPreviewSrc ? (
                          <img className="inv-design-element__barcode-image" src={qrPreviewSrc} alt="QR preview" draggable={false} />
                        ) : null}
                      </span>
                    </>
                  ) : isImage ? (
                    <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden', border: element.static_content ? 'none' : '1px dashed rgba(255,255,255,0.3)', background: element.static_content ? 'transparent' : 'rgba(0,0,0,0.2)', borderRadius: 4 }}>
                      {element.static_content ? (
                        <img src={element.static_content} alt={element.label || 'Logo'} style={{ width: '100%', height: '100%', objectFit: 'contain' }} draggable={false} />
                      ) : (
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, color: 'rgba(255,255,255,0.6)', fontSize: 10 }}>
                          <ImageIcon size={18} />
                          <span>شعار / صورة</span>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="inv-design-element__text-preview" style={{
                      fontFamily: `'${element.font_family || 'Cairo'}', 'Cairo', 'Noto Sans Arabic', sans-serif`,
                      fontSize: `${element.font_size ?? 20}px`,
                      color: element.font_color || '#374151',
                      textAlign: (element.text_align as any) || 'center',
                      direction: element.text_direction === 'ltr' ? 'ltr' : 'rtl',
                      fontWeight: element.font_weight || 'normal',
                      lineHeight: element.line_height ?? 1.2,
                      padding: '4px 8px',
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                    }}>
                      {previewMode
                        ? (element.element_type === 'guest_name' ? 'محمد عبدالله العمري'
                          : element.element_type === 'dynamic_text' ? (element.data_key ? `بيانات: ${element.data_key}` : 'نص ديناميكي')
                          : element.element_type === 'event_date' ? 'السبت 28 / 6 / 2025'
                          : element.element_type === 'event_time' ? '07:00 مساءً'
                          : element.element_type === 'event_location' ? 'فندق الريتز كارلتون'
                          : element.element_type === 'event_address' ? 'طريق الملك فهد، حي العليا'
                          : element.element_type === 'seat_number' ? 'A-12'
                          : element.static_content || element.label)
                        : (element.static_content || element.label || `{${element.data_key || element.element_type}}`)}
                    </div>
                  )}
                  {isSelected && (
                    <span
                      className="inv-design-element__resize-handle inv-design-element__resize-handle--se"
                      onMouseDown={(e) => {
                        e.preventDefault()
                        e.stopPropagation()
                        const viewportBox = viewportRef.current?.getBoundingClientRect()
                        if (!viewportBox) return
                        dragRef.current = {
                          id: element.id,
                          mode: 'resize',
                          offsetX: 0,
                          offsetY: 0,
                          startClientX: e.clientX,
                          startClientY: e.clientY,
                          startWorldX: (e.clientX - viewportBox.left - viewTransform.panX) / viewTransform.zoom,
                          startWorldY: (e.clientY - viewportBox.top - viewTransform.panY) / viewTransform.zoom,
                          startX: element.x * canvasWidth,
                          startY: element.y * canvasHeight,
                          startWidth: element.width * canvasWidth,
                          startHeight: element.height * canvasHeight,
                          startFontSize: element.font_size ?? 20,
                        }
                        setSelectedId(element.id)
                      }}
                      title="تغيير الحجم"
                    />
                  )}
                </button>
              )
            })}
            </div>
          </div>
        </section>

        <aside className="inv-design-sidebar-right">


          {selectedElement ? (
            <div className="inv-design-inspector" style={{ background: 'transparent', border: 'none', padding: 0 }}>
              <div className="inv-design-inspector__head" style={{ marginBottom: 10 }}>
                <strong>{selectedElement.label || selectedElement.element_type}</strong>
                <div className="inv-design-inspector__actions">
                  {selectedElement.element_type === 'qr_code' && (
                    <button
                      type="button"
                      className="inv-quick-modal__close"
                      onClick={() => setQrPreviewVisible((prev) => !prev)}
                      disabled={isSaving}
                      title={qrPreviewVisible ? 'إخفاء QR' : 'إظهار QR'}
                    >
                      {qrPreviewVisible ? <EyeOff size={14} /> : <Eye size={14} />}
                    </button>
                  )}
                  <button type="button" className="inv-quick-modal__close" onClick={duplicateSelected} disabled={isSaving} title="نسخ العنصر">
                    <Move size={14} />
                  </button>
                  <button type="button" className="inv-quick-modal__close" onClick={deleteSelected} disabled={isSaving} title="حذف العنصر">
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>

              {/* Dynamic text / Guest name elements: data_key selector */}
              {(selectedElement.element_type === 'dynamic_text' || selectedElement.element_type === 'guest_name') && (
                <div style={{ marginBottom: 10 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                    <label className="inv-label" style={{ marginBottom: 0 }}>
                      {selectedElement.element_type === 'guest_name' ? 'عمود اسم الضيف في Excel' : 'ربط الحقل بعمود البيانات (data_key)'}
                    </label>
                    {(excelColumns.length > 0 || uploadedExcelName) && (
                      <button
                        type="button"
                        className="btn btn-ghost"
                        style={{ fontSize: 10, padding: '2px 6px', height: 'auto', color: 'var(--color-primary)' }}
                        onClick={() => setIsManualKey(p => !p)}
                      >
                        {isManualKey ? '📋 اختيار من القائمة' : '✍️ كتابة يدوية'}
                      </button>
                    )}
                  </div>

                  {!isManualKey && (excelColumns.length > 0) ? (
                    <div className="inv-design-select-wrap">
                      <select
                        className="inv-input inv-design-select"
                        value={selectedElement.data_key || ''}
                        onChange={(e) => {
                          const val = e.target.value
                          if (val === '__manual__') {
                            setIsManualKey(true)
                          } else {
                            updateSelected({ data_key: val })
                          }
                        }}
                        disabled={isSaving}
                      >
                        <option value="">-- اختر عموداً من ملف Excel --</option>
                        {excelColumns.map((col) => (
                          <option key={col} value={col}>
                            {col}
                          </option>
                        ))}
                        <option value="__manual__">-- ✍️ كتابة مفتاح مخصص يدوياً --</option>
                      </select>
                      <ChevronDown size={14} className="inv-design-select-icon" />
                    </div>
                  ) : (
                    <div>
                      <input
                        className="inv-input"
                        placeholder="مثال: اسم الضيف أو guest.name"
                        value={selectedElement.data_key || ''}
                        onChange={(e) => updateSelected({ data_key: e.target.value })}
                        disabled={isSaving}
                      />
                      {excelColumns.length === 0 && (
                        <div style={{ display: 'flex', gap: 4, marginTop: 6, flexWrap: 'wrap' }}>
                          {['guest.name', 'custom.seat', 'custom.table', 'custom.hall'].map((key) => (
                            <button
                              key={key}
                              type="button"
                              className="btn btn-ghost"
                              style={{ fontSize: 9, padding: '2px 6px', height: 'auto', background: 'rgba(0,0,0,0.05)' }}
                              onClick={() => updateSelected({ data_key: key })}
                            >
                              {key}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  <span style={{ fontSize: 10, color: 'var(--color-text-muted)', marginTop: 4, display: 'block' }}>
                    {excelColumns.length > 0 
                      ? `تم تحميل أعمدة ملفك: "${uploadedExcelName}". اختر العمود المراد طباعة بياناته في هذا الموضع.`
                      : 'اكتب اسم العمود كما هو في ملف الأكسل، أو ارفع ملفك في القائمة الجانبية لقراءته تلقائياً.'}
                  </span>
                </div>
              )}

              {/* Field formatting for dynamic text */}
              {selectedElement.element_type === 'dynamic_text' && (
                <div style={{ marginBottom: 10 }}>
                  <label className="inv-label">تنسيق الحقل (نوع البيانات)</label>
                  <div className="inv-design-select-wrap">
                    <select
                      className="inv-input inv-design-select"
                      value={selectedElement.static_content || 'text'}
                      onChange={(e) => updateSelected({ static_content: e.target.value })}
                      disabled={isSaving}
                    >
                      <option value="text">نص عادي (عام)</option>
                      <option value="date">تاريخ (تنسيق تاريخ YYYY-MM-DD)</option>
                      <option value="time">وقت (تنسيق وقت HH:MM)</option>
                      <option value="number">رقم</option>
                    </select>
                    <ChevronDown size={14} className="inv-design-select-icon" />
                  </div>
                  <span style={{ fontSize: 10, color: 'var(--color-text-muted)', marginTop: 4, display: 'block' }}>
                    اختر نوع التنسيق ليتم عرض وعرض البيانات بالنمط الصحيح عند توليد البطاقات.
                  </span>
                </div>
              )}

              {/* Slot index: link dynamic text to a specific barcode */}
              {(selectedElement.element_type === 'dynamic_text' || selectedElement.element_type === 'guest_name') && (() => {
                const barcodes = elements.filter(e => e.element_type === 'qr_code' || e.element_type === 'barcode')
                if (barcodes.length === 0) return null
                return (
                  <div style={{ marginBottom: 10 }}>
                    <label className="inv-label">ربط بالباركود</label>
                    <div className="inv-design-select-wrap">
                      <select
                        className="inv-input inv-design-select"
                        value={selectedElement.slot_index ?? 'auto'}
                        onChange={(e) => {
                          const val = e.target.value
                          if (val === 'auto') {
                            const nearest = findNearestBarcodeSlot(selectedElement, elements)
                            updateSelected({ slot_index: nearest ?? undefined } as any)
                          } else {
                            updateSelected({ slot_index: parseInt(val) } as any)
                          }
                        }}
                        disabled={isSaving}
                      >
                        <option value="auto">تلقائي (أقرب باركود)</option>
                        {barcodes.map((bc, idx) => (
                          <option key={bc.id} value={idx}>
                            {bc.label || `باركود ${idx + 1}`} (Slot {idx})
                          </option>
                        ))}
                      </select>
                      <ChevronDown size={14} className="inv-design-select-icon" />
                    </div>
                    <span style={{ fontSize: 10, color: 'var(--color-text-muted)', marginTop: 4, display: 'block' }}>
                      اختر أي باركود سيعرض بيانات نفس الضيف مع هذا النص
                    </span>
                  </div>
                )
              })()}

              {selectedElement.element_type === 'custom_text' && (
                <div style={{ marginBottom: 10 }}>
                  <label className="inv-label">النص</label>
                  <input
                    className="inv-input"
                    placeholder="اكتب النص هنا"
                    value={selectedElement.static_content || ''}
                    onChange={(e) => updateSelected({ static_content: e.target.value })}
                    disabled={isSaving}
                  />
                  {event && (
                    <div style={{ marginTop: 8 }}>
                      <label className="inv-label" style={{ fontSize: 11, color: 'rgba(255,255,255,0.5)', marginBottom: 6, display: 'block' }}>
                        ✨ إدراج سريع من بيانات الحفل:
                      </label>
                      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                        {[
                          { label: 'اسم الحفل', value: event.title_ar || event.title },
                          {
                            label: 'التاريخ',
                            value: event.start_date
                              ? new Date(event.start_date).toLocaleDateString('ar-SA', { year: 'numeric', month: '2-digit', day: '2-digit' })
                              : '',
                          },
                          {
                            label: 'اليوم',
                            value: event.start_date
                              ? new Date(event.start_date).toLocaleDateString('ar-SA', { weekday: 'long' })
                              : '',
                          },
                          {
                            label: 'الوقت',
                            value: event.start_date
                              ? new Date(event.start_date).toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' })
                              : '',
                          },
                          { label: 'القاعة/المقر', value: event.venue_name_ar || event.venue_name || '' },
                          { label: 'العنوان', value: event.venue_address || '' },
                          { label: 'المدينة', value: event.venue_city || '' },
                        ]
                          .filter((item) => item.value)
                          .map((item) => (
                            <button
                              key={item.label}
                              type="button"
                              className="btn btn-ghost"
                              style={{
                                fontSize: 9,
                                padding: '3px 8px',
                                height: 'auto',
                                background: 'rgba(201, 169, 110, 0.08)',
                                border: '1px solid rgba(201, 169, 110, 0.2)',
                                color: '#C9A96E',
                                borderRadius: 6,
                                cursor: 'pointer',
                              }}
                              onClick={() => updateSelected({ static_content: item.value })}
                              title={item.value}
                            >
                              {item.label}
                            </button>
                          ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Image upload controls for logo/image elements */}
              {selectedElement.element_type === 'image' && (
                <div style={{ marginBottom: 10 }}>
                  <label className="inv-label">صورة الشعار / التصميم</label>
                  
                  {selectedElement.static_content ? (
                    <div style={{ marginBottom: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
                      <div style={{ width: '100%', height: 100, borderRadius: 6, overflow: 'hidden', background: '#1f2937', border: '1px solid rgba(255,255,255,0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        <img src={selectedElement.static_content} alt="Preview" style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }} />
                      </div>
                      <button
                        type="button"
                        className="btn btn-ghost"
                        style={{ width: '100%', border: '1px dashed rgba(255,255,255,0.2)', fontSize: 12, height: 32, gap: 4 }}
                        onClick={() => {
                          const input = document.createElement('input')
                          input.type = 'file'
                          input.accept = 'image/*'
                          const elementId = selectedElement.id
                          const elementWidth = selectedElement.width
                          input.onchange = async (e) => {
                            const file = (e.target as HTMLInputElement).files?.[0]
                            if (file) {
                              const previewUrl = URL.createObjectURL(file)
                              setIsUploadingAsset(true)
                              
                              try {
                                const img = new Image()
                                img.onload = () => {
                                  const ratio = img.naturalWidth / img.naturalHeight
                                  const currentWidthPx = elementWidth * canvasWidth
                                  const nextHeightPx = currentWidthPx / ratio
                                  updateElementById(elementId, {
                                    static_content: previewUrl,
                                    height: nextHeightPx / canvasHeight
                                  })
                                }
                                img.src = previewUrl

                                const tmplId = await ensureTemplateId()
                                const uploadedAsset = await templatesApi.uploadAsset(tmplId, file, 'logo')
                                
                                updateElementById(elementId, {
                                  static_content: uploadedAsset.file_url
                                })
                              } catch (err) {
                                console.error('Failed to upload image asset:', err)
                                setModalAlert({
                                  title: 'خطأ في الرفع',
                                  message: 'فشل رفع الشعار إلى الخادم. يرجى المحاولة مرة أخرى.',
                                  type: 'error'
                                })
                              } finally {
                                setIsUploadingAsset(false)
                              }
                            }
                          }
                          input.click()
                        }}
                        disabled={isSaving || isUploadingAsset}
                      >
                        <Upload size={14} /> تغيير الصورة
                      </button>
                    </div>
                  ) : (
                    <label className="inv-upload-btn inv-design-upload" style={{ display: 'flex', justifyContent: 'center', height: 60, alignItems: 'center', cursor: isSaving || isUploadingAsset ? 'not-allowed' : 'pointer', opacity: isSaving || isUploadingAsset ? 0.6 : 1 }}>
                      <Upload size={16} style={{ marginLeft: 6 }} /> رفع ملف الصورة
                      <input
                        type="file"
                        accept="image/*"
                        hidden
                        onChange={async (e) => {
                          const file = e.target.files?.[0]
                          if (file) {
                            const previewUrl = URL.createObjectURL(file)
                            const elementId = selectedElement.id
                            const elementWidth = selectedElement.width
                            setIsUploadingAsset(true)
                            
                            try {
                              const img = new Image()
                              img.onload = () => {
                                const ratio = img.naturalWidth / img.naturalHeight
                                const currentWidthPx = elementWidth * canvasWidth
                                const nextHeightPx = currentWidthPx / ratio
                                updateElementById(elementId, {
                                  static_content: previewUrl,
                                  height: nextHeightPx / canvasHeight
                                })
                              }
                              img.src = previewUrl

                              const tmplId = await ensureTemplateId()
                              const uploadedAsset = await templatesApi.uploadAsset(tmplId, file, 'logo')
                              
                              updateElementById(elementId, {
                                static_content: uploadedAsset.file_url
                              })
                            } catch (err) {
                              console.error('Failed to upload image asset:', err)
                              setModalAlert({
                                  title: 'خطأ في الرفع',
                                  message: 'فشل رفع الشعار إلى الخادم. يرجى المحاولة مرة أخرى.',
                                  type: 'error'
                              })
                            } finally {
                              setIsUploadingAsset(false)
                            }
                          }
                        }}
                        disabled={isSaving || isUploadingAsset}
                      />
                    </label>
                  )}

                  <div style={{ marginTop: 8 }}>
                    <label className="inv-label" style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>أو أدخل رابط الصورة مباشرة</label>
                    <input
                      className="inv-input"
                      placeholder="رابط الصورة (URL)"
                      value={selectedElement.static_content?.startsWith('blob:') ? '' : selectedElement.static_content || ''}
                      onChange={(e) => {
                        const val = e.target.value
                        const elementId = selectedElement.id
                        const elementWidth = selectedElement.width
                        updateElementById(elementId, { static_content: val })
                        if (val && (val.startsWith('http://') || val.startsWith('https://') || val.startsWith('data:'))) {
                          const img = new Image()
                          img.onload = () => {
                            const ratio = img.naturalWidth / img.naturalHeight
                            const currentWidthPx = elementWidth * canvasWidth
                            const nextHeightPx = currentWidthPx / ratio
                            updateElementById(elementId, {
                              static_content: val,
                              height: nextHeightPx / canvasHeight
                            })
                          }
                          img.src = val
                        }
                      }}
                      disabled={isSaving || isUploadingAsset}
                    />
                  </div>
                </div>
              )}

              {/* ═══ Typography Controls (text elements only) ═══ */}
              {selectedElement.element_type !== 'qr_code' && selectedElement.element_type !== 'barcode' && selectedElement.element_type !== 'image' && (
                <>
                  {/* Font Family */}
                  <div style={{ marginBottom: 10 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                      <label className="inv-label" style={{ marginBottom: 0 }}>نوع الخط</label>
                      <label style={{
                        fontSize: 11,
                        color: 'var(--color-primary)',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 2,
                        fontWeight: '500'
                      }}>
                        <Upload size={12} />
                        <span>رفع خط جديد (.ttf)</span>
                        <input
                          type="file"
                          accept=".ttf,.otf"
                          style={{ display: 'none' }}
                          onChange={handleFontUpload}
                          disabled={isUploadingFont}
                        />
                      </label>
                    </div>
                    <div className="inv-design-select-wrap">
                      <select
                        className="inv-input inv-design-select"
                        value={selectedElement.font_family || 'Cairo'}
                        onChange={(e) => updateSelected({ font_family: e.target.value })}
                        disabled={isSaving || isUploadingFont}
                      >
                        {fontsList.map((f) => (
                          <option key={f.value} value={f.value}>{f.label}</option>
                        ))}
                      </select>
                      <ChevronDown size={14} className="inv-design-select-icon" />
                    </div>
                    {isUploadingFont && (
                      <span style={{ fontSize: 10, color: 'var(--color-text-muted)', marginTop: 2, display: 'block' }}>
                        جاري رفع الخط...
                      </span>
                    )}
                  </div>

                  {/* Font Size + Weight */}
                  <div className="inv-design-split" style={{ marginBottom: 10 }}>
                    <div>
                      <label className="inv-label">حجم الخط</label>
                      <input
                        className="inv-input"
                        type="number"
                        min={8}
                        max={120}
                        value={selectedElement.font_size ?? 20}
                        onChange={(e) => updateSelected({ font_size: parseInt(e.target.value) || 20 })}
                        disabled={isSaving || isUploadingFont}
                      />
                    </div>
                    <div>
                      <label className="inv-label">الوزن</label>
                      <button
                        type="button"
                        className={`inv-design-toggle-btn ${selectedElement.font_weight === 'bold' ? 'inv-design-toggle-btn--active' : ''}`}
                        onClick={() => updateSelected({ font_weight: selectedElement.font_weight === 'bold' ? 'normal' : 'bold' })}
                        disabled={isSaving || isUploadingFont}
                        title="خط عريض"
                      >
                        <Bold size={16} />
                        {selectedElement.font_weight === 'bold' ? 'عريض' : 'عادي'}
                      </button>
                    </div>
                  </div>

                  {/* Font Color */}
                  <div style={{ marginBottom: 10 }}>
                    <label className="inv-label">لون الخط</label>
                    <div className="inv-design-color-row">
                      <input
                        className="inv-design-color-swatch"
                        type="color"
                        value={selectedElement.font_color || '#ffffff'}
                        onChange={(e) => updateSelected({ font_color: e.target.value })}
                        disabled={isSaving}
                      />
                      <input
                        className="inv-input inv-design-color-hex"
                        value={selectedElement.font_color || '#ffffff'}
                        onChange={(e) => updateSelected({ font_color: e.target.value })}
                        disabled={isSaving}
                        placeholder="#ffffff"
                      />
                    </div>
                  </div>

                  {/* Text Alignment */}
                  <div style={{ marginBottom: 10 }}>
                    <label className="inv-label">محاذاة النص</label>
                    <div className="inv-design-align-group">
                      <button
                        type="button"
                        className={`inv-design-align-btn ${selectedElement.text_align === 'right' ? 'inv-design-align-btn--active' : ''}`}
                        onClick={() => updateSelected({ text_align: 'right' })}
                        disabled={isSaving}
                        title="محاذاة لليمين"
                      >
                        <AlignRight size={16} />
                      </button>
                      <button
                        type="button"
                        className={`inv-design-align-btn ${selectedElement.text_align === 'center' ? 'inv-design-align-btn--active' : ''}`}
                        onClick={() => updateSelected({ text_align: 'center' })}
                        disabled={isSaving}
                        title="محاذاة للوسط"
                      >
                        <AlignCenter size={16} />
                      </button>
                      <button
                        type="button"
                        className={`inv-design-align-btn ${selectedElement.text_align === 'left' ? 'inv-design-align-btn--active' : ''}`}
                        onClick={() => updateSelected({ text_align: 'left' })}
                        disabled={isSaving}
                        title="محاذاة لليسار"
                      >
                        <AlignLeft size={16} />
                      </button>
                    </div>
                  </div>

                  {/* Text Direction */}
                  <div style={{ marginBottom: 10 }}>
                    <label className="inv-label">اتجاه النص</label>
                    <div className="inv-design-align-group">
                      <button
                        type="button"
                        className={`inv-design-align-btn ${selectedElement.text_direction === 'rtl' ? 'inv-design-align-btn--active' : ''}`}
                        onClick={() => updateSelected({ text_direction: 'rtl' })}
                        disabled={isSaving}
                      >
                        RTL
                      </button>
                      <button
                        type="button"
                        className={`inv-design-align-btn ${selectedElement.text_direction === 'ltr' ? 'inv-design-align-btn--active' : ''}`}
                        onClick={() => updateSelected({ text_direction: 'ltr' })}
                        disabled={isSaving}
                      >
                        LTR
                      </button>
                    </div>
                  </div>
                </>
              )}

              {/* ═══ Position & Size ═══ */}
              <div style={{ marginTop: 6 }}>
                <label className="inv-label" style={{ fontSize: 11, opacity: 0.7, letterSpacing: '0.05em', textTransform: 'uppercase' }}>الموقع والحجم</label>
              </div>
              <div className="inv-design-split">
                <div>
                  <label className="inv-label">X</label>
                  <input className="inv-input" type="number" step="0.01" min={0} max={1} value={selectedElement.x} onChange={(e) => updateSelected({ x: Math.max(0, Math.min(1, parseFloat(e.target.value) || 0)) })} />
                </div>
                <div>
                  <label className="inv-label">Y</label>
                  <input className="inv-input" type="number" step="0.01" min={0} max={1} value={selectedElement.y} onChange={(e) => updateSelected({ y: Math.max(0, Math.min(1, parseFloat(e.target.value) || 0)) })} />
                </div>
              </div>
              <div className="inv-design-split">
                <div>
                  <label className="inv-label">العرض</label>
                  <input className="inv-input" type="number" step="0.01" min={0.02} max={1} value={selectedElement.width} onChange={(e) => updateSelected({ width: Math.max(0.02, Math.min(1, parseFloat(e.target.value) || 0.1)) })} />
                </div>
                <div>
                  <label className="inv-label">الارتفاع</label>
                  <input className="inv-input" type="number" step="0.01" min={0.02} max={1} value={selectedElement.height} onChange={(e) => updateSelected({ height: Math.max(0.02, Math.min(1, parseFloat(e.target.value) || 0.1)) })} />
                </div>
              </div>

            </div>
          ) : (
            <div style={{ textAlign: 'center', color: 'var(--color-text-muted)', marginTop: 40, fontSize: 13 }}>
              اختر عنصراً من مساحة العمل لتعديل خصائصه
            </div>
          )}
          <LimitErrorNotice error={localError} />
        </aside>
      </div>

      {showSaveSuccessModal && (() => {
        const hasCustomFields = elements.some(el =>
          (el.element_type === 'dynamic_text' || el.element_type === 'guest_name') &&
          el.data_key && el.data_key.trim() !== ''
        )
        return (
        <div className="inv-quick-modal-overlay" role="dialog" aria-modal="true">
          <div className="inv-quick-modal" style={{ width: '460px', padding: '24px' }}>
            <div className="inv-quick-modal__header">
              <div>
                <h3 style={{ fontSize: '20px', fontWeight: 'bold', color: '#10b981', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span style={{ fontSize: '24px' }}>✓</span> تم حفظ التصميم بنجاح!
                </h3>
                <p style={{ marginTop: '8px', fontSize: '13px', lineHeight: '1.6', color: 'rgba(255,255,255,0.7)' }}>
                  {hasCustomFields
                    ? `تم حفظ قالب البطاقة "${templateName}". يمكنك الآن تحميل ملف Excel المخصص لهذا التصميم والذي يحتوي على كافة الحقول المخصصة التي قمت بإضافتها لملئها ورفعها لاحقاً.`
                    : `تم حفظ قالب البطاقة "${templateName}" بنجاح. يمكنك الآن المتابعة لإصدار الدعوات.`
                  }
                </p>
              </div>
            </div>
            
            <div className="inv-quick-modal__body" style={{ marginTop: '16px', gap: '12px' }}>
              {hasCustomFields && (
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => {
                    downloadCustomExcelTemplate()
                  }}
                  style={{
                    width: '100%',
                    background: '#10b981',
                    borderColor: '#10b981',
                    color: '#fff',
                    justifyContent: 'center',
                    padding: '12px',
                    fontWeight: '600',
                    gap: '8px',
                    display: 'flex',
                    alignItems: 'center'
                  }}
                >
                  <Upload size={16} style={{ transform: 'rotate(180deg)' }} />
                  تنزيل نموذج Excel المخصص للتصميم
                </button>
              )}
              
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => {
                  setShowSaveSuccessModal(false)
                  if (editingTemplateId) {
                    navigate(`/events/${event.id}?tab=templates`)
                  } else {
                    navigate(`/events/${event.id}?tab=invitations&source=design&templateId=${savedTemplateId || editingTemplateId}&ticketClass=${activeTab}`)
                  }
                }}
                style={{
                  width: '100%',
                  justifyContent: 'center',
                  padding: '12px',
                  borderColor: 'rgba(255,255,255,0.1)',
                  color: 'rgba(255,255,255,0.8)'
                }}
              >
                متابعة لإصدار الدعوات
              </button>
            </div>
          </div>
        </div>
        )
      })()}

      {modalAlert && (
        <div className="inv-quick-modal-overlay" role="dialog" aria-modal="true" style={{ zIndex: 11000 }}>
          <div className="inv-quick-modal" style={{ width: '400px', padding: '20px' }}>
            <div className="inv-quick-modal__header" style={{ marginBottom: '12px' }}>
              <div>
                <h3 style={{
                  fontSize: '18px',
                  fontWeight: 'bold',
                  color: modalAlert.type === 'success' ? '#10b981' : modalAlert.type === 'error' ? '#ef4444' : '#3b82f6',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px'
                }}>
                  {modalAlert.type === 'success' ? '✓' : modalAlert.type === 'error' ? '⚠' : 'ℹ'} {modalAlert.title}
                </h3>
              </div>
            </div>
            <div className="inv-quick-modal__body" style={{ fontSize: '13px', color: 'rgba(255, 255, 255, 0.7)', lineHeight: '1.6', marginBottom: '16px' }}>
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
                  background: modalAlert.type === 'success' ? '#10b981' : modalAlert.type === 'error' ? '#ef4444' : 'var(--color-primary)',
                  borderColor: modalAlert.type === 'success' ? '#10b981' : modalAlert.type === 'error' ? '#ef4444' : 'var(--color-primary)',
                  color: '#fff',
                  padding: '10px',
                  fontWeight: '600'
                }}
              >
                موافق
              </button>
            </div>
          </div>
        </div>
      )}
    </WorkspaceShell>
  )
}
