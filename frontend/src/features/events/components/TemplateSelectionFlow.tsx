/**
 * TemplateSelectionFlow.tsx — محسّن مع ربط ديناميكي من عناصر القالب
 * 🎯 نظام احترافي وسلس لاختيار نوع الدعوات ثم القالب
 *
 * التحسينات:
 * - جلب عناصر القالب بعد اختياره واستخراج data_key من كل عنصر dynamic_text
 * - ربط ديناميكي بدلاً من 4 حقول ثابتة
 * - Auto-detect أذكى يطابق data_key مع أسماء أعمدة Excel
 * - معاينة مع بيانات Excel الفعلية
 */

import { useState, useEffect, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useAuthStore } from '@features/auth/store/authStore'
import { templatesApi } from '../api/templatesApi'
import {
  Upload, CheckCircle2, AlertCircle, ChevronRight, ChevronLeft,
  Loader2, Crown, Users
} from 'lucide-react'
import './template-selection-flow.css'
import './invitation-type-selection.css'
import { 
  getCleanFieldLabel, 
  resolveGuestName, 
  resolveGuestCount, 
  resolveTicketClass,
  formatCellValue
} from '../utils/mappingUtils'
import { readSpreadsheet } from '../utils/spreadsheet'

interface TemplateSelectionFlowProps {
  eventId: string
  onComplete: (data: {
    invitationType: 'vip' | 'normal'
    templateId: string
    templateName: string
    guests: Array<{
      guest_name: string
      [key: string]: string
    }>
    columnMapping: Record<string, string>
  }) => void
  onCancel: () => void
}

type Step = 'type' | 'template' | 'upload' | 'mapping' | 'preview'
type InvitationType = 'vip' | 'normal'

interface ExcelColumn {
  name: string
  index: number
  sampleValues: string[]
}

/** A field derived from the template's dynamic_text / guest_name elements */
interface DynamicField {
  data_key: string
  label: string
  element_type: string
  required: boolean // guest_name is always required
}

interface InvitationTypeOption {
  id: InvitationType
  label: string
  description: string
  icon: React.ReactNode
}

// ── Built-in fields that always exist (even without template elements)
const BUILTIN_FIELDS: DynamicField[] = [
  { data_key: 'guest.name', label: 'اسم الضيف', element_type: 'guest_name', required: true },
]

// ── Known aliases for auto-detect
const ALIAS_MAP: Record<string, string[]> = {
  'guest.name': ['اسم الضيف', 'guest_name', 'name', 'اسم', 'الاسم', 'guestname', 'الضيف'],
  'event.date': ['تاريخ', 'event_date', 'date', 'التاريخ', 'eventdate'],
  'event.time': ['وقت', 'event_time', 'time', 'الوقت', 'eventtime'],
  'custom.seat': ['مقعد', 'seat_number', 'seat', 'رقم المقعد', 'seatnumber', 'المقعد'],
  'custom.table': ['طاولة', 'table_number', 'table', 'رقم الطاولة'],
  'custom.gate': ['بوابة', 'gate', 'البوابة'],
  'custom.hall': ['قاعة', 'hall', 'القاعة'],
}

export function TemplateSelectionFlow({ eventId, onComplete, onCancel }: TemplateSelectionFlowProps) {
  const [currentStep, setCurrentStep] = useState<Step>('type')
  const [invitationType, setInvitationType] = useState<InvitationType | null>(null)
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>('')
  const [selectedTemplateName, setSelectedTemplateName] = useState<string>('')
  const [uploadedFile, setUploadedFile] = useState<File | null>(null)
  const [excelColumns, setExcelColumns] = useState<ExcelColumn[]>([])
  const [excelRows, setExcelRows] = useState<Record<string, string>[]>([])
  const [columnMapping, setColumnMapping] = useState<Record<string, string>>({})
  const [mappingErrors, setMappingErrors] = useState<string[]>([])
  const [isProcessing, setIsProcessing] = useState(false)

  // Dynamic fields extracted from template elements
  const [dynamicFields, setDynamicFields] = useState<DynamicField[]>(BUILTIN_FIELDS)
  const [templateElements, setTemplateElements] = useState<any[]>([])
  const [hoveredFieldKey, setHoveredFieldKey] = useState<string | null>(null)

  const tenantId = useAuthStore((s) => s.currentTenantId)

  // جلب جميع القوالب
  const { data: allTemplates = [], isLoading: templatesLoading } = useQuery({
    queryKey: ['templates', eventId, tenantId],
    queryFn: () => templatesApi.list(eventId),
    enabled: !!tenantId,
  })

  const selectedTemplate = allTemplates.find((t) => t.id === selectedTemplateId)

  // تصفية القوالب حسب النوع المختار
  const templates = invitationType
    ? allTemplates.filter((t) => {
        const tc = (t as any).ticket_class || 'normal'
        return tc === invitationType || t.template_type === 'quick'
      })
    : []

  const invitationTypes: InvitationTypeOption[] = [
    {
      id: 'vip',
      label: '👑 دعوات VIP',
      description: 'دعوات فاخرة مميزة للضيوف المهمين',
      icon: <Crown size={48} />,
    },
    {
      id: 'normal',
      label: '👥 دعوات عادية',
      description: 'دعوات عادية للضيوف العاديين',
      icon: <Users size={48} />,
    },
  ]

  // ── Fetch template elements when a template is selected
  useEffect(() => {
    if (!selectedTemplateId) {
      setDynamicFields(BUILTIN_FIELDS)
      setTemplateElements([])
      return
    }

    let cancelled = false
    templatesApi.getElements(selectedTemplateId).then((elements) => {
      if (cancelled) return
      setTemplateElements(elements)

      // Extract dynamic fields from template elements
      const fields: DynamicField[] = []
      const seenKeys = new Set<string>()

      for (const el of elements) {
        if (el.element_type === 'guest_name') {
          const key = el.data_key || 'guest.name'
          if (!seenKeys.has(key)) {
            seenKeys.add(key)
            fields.push({
              data_key: key,
              label: getCleanFieldLabel(key, el.element_type, el.label),
              element_type: el.element_type,
              required: true,
            })
          }
        } else if (el.element_type === 'dynamic_text' && el.data_key) {
          if (!seenKeys.has(el.data_key)) {
            seenKeys.add(el.data_key)
            fields.push({
              data_key: el.data_key,
              label: getCleanFieldLabel(el.data_key, el.element_type, el.label),
              element_type: el.element_type,
              required: false,
            })
          }
        } else if (['event_date', 'event_time', 'event_location', 'seat_number', 'gate', 'hall', 'table_number'].includes(el.element_type)) {
          const key = el.data_key || `custom.${el.element_type}`
          if (!seenKeys.has(key)) {
            seenKeys.add(key)
            fields.push({
              data_key: key,
              label: getCleanFieldLabel(key, el.element_type, el.label),
              element_type: el.element_type,
              required: false,
            })
          }
        }
      }

      setDynamicFields(fields.length > 0 ? fields : BUILTIN_FIELDS)
    }).catch(() => {
      if (!cancelled) {
        setDynamicFields(BUILTIN_FIELDS)
        setTemplateElements([])
      }
    })

    return () => { cancelled = true }
  }, [selectedTemplateId])

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  // الخطوة 1: اختيار نوع الدعوات
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  const handleTypeSelect = (type: InvitationType) => {
    setInvitationType(type)
    setCurrentStep('template')
    setSelectedTemplateId('')
    setSelectedTemplateName('')
  }

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  // الخطوة 2: اختيار القالب
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  const handleTemplateSelect = (templateId: string, templateName: string) => {
    setSelectedTemplateId(templateId)
    setSelectedTemplateName(templateName)
  }

  const handleTemplateNext = () => {
    if (!selectedTemplateId) {
      alert('يرجى اختيار قالب')
      return
    }
    setCurrentStep('upload')
  }

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  // الخطوة 3: تحميل الملف
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  const handleFileSelect = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return

    if (!file.name.endsWith('.xlsx') && !file.name.endsWith('.csv')) {
      alert('يرجى اختيار ملف Excel (.xlsx) أو CSV (.csv)')
      return
    }

    setIsProcessing(true)
    try {
      setUploadedFile(file)

      const data = (await readSpreadsheet(file)).map((row) =>
        Object.fromEntries(
          Object.entries(row).map(([key, value]) => [key, String(value ?? '')]),
        ),
      )

      if (data.length === 0) {
        alert('الملف فارغ')
        return
      }

      const columnNames = Object.keys(data[0])
      const columns: ExcelColumn[] = columnNames.map((name, index) => ({
        name,
        index,
        sampleValues: data.slice(0, 3).map((row) => row[name] || ''),
      }))

      setExcelColumns(columns)
      setExcelRows(data)

      autoDetectMapping(columns)

      setCurrentStep('mapping')
    } catch (error) {
      alert(`خطأ في قراءة الملف: ${error instanceof Error ? error.message : 'خطأ غير معروف'}`)
    } finally {
      setIsProcessing(false)
    }
  }

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  // الاستخراج التلقائي للبيانات (ذكي — يطابق data_key مع أسماء أعمدة Excel)
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  const validateMapping = useCallback((mapping: Record<string, string>) => {
    const errors: string[] = []

    for (const field of dynamicFields) {
      if (field.required && !mapping[field.data_key]) {
        errors.push(`حقل مطلوب: ${field.label}`)
      }
    }

    setMappingErrors(errors)
  }, [dynamicFields])

  const autoDetectMapping = useCallback((columns: ExcelColumn[]) => {
    const mapping: Record<string, string> = {}

    for (const field of dynamicFields) {
      const match = findMatchingColumn(field.data_key, field.label, columns)
      if (match) {
        mapping[field.data_key] = match
      }
    }

    setColumnMapping(mapping)
    validateMapping(mapping)
  }, [dynamicFields, validateMapping])

  const findMatchingColumn = (dataKey: string, label: string, columns: ExcelColumn[]): string | null => {
    // 1. Check known aliases
    const aliases = ALIAS_MAP[dataKey] || []
    // Also add the label and data_key itself as potential matches
    const potentialMatches = [...aliases, label, dataKey]

    // Exact match first
    for (const col of columns) {
      const colLower = col.name.toLowerCase().trim()
      if (potentialMatches.some((alias) => colLower === alias.toLowerCase())) {
        return col.name
      }
    }

    // Partial match
    for (const col of columns) {
      const colLower = col.name.toLowerCase().trim()
      if (potentialMatches.some((alias) =>
        colLower.includes(alias.toLowerCase()) || alias.toLowerCase().includes(colLower)
      )) {
        return col.name
      }
    }

    return null
  }

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  // الخطوة 4: تعديل التعيين
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  const handleMappingChange = (dataKey: string, columnName: string) => {
    const newMapping = { ...columnMapping, [dataKey]: columnName }
    setColumnMapping(newMapping)
    validateMapping(newMapping)
  }

  const handleMappingNext = () => {
    if (mappingErrors.length > 0) {
      alert('يرجى ملء جميع الحقول المطلوبة')
      return
    }
    setCurrentStep('preview')
  }

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  // الخطوة 5: المعاينة والتأكيد
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  const getPreviewData = () => {
    return excelRows.slice(0, 5).map((row) => {
      const result: Record<string, string> = {}
      for (const field of dynamicFields) {
        const colName = columnMapping[field.data_key]
        result[field.data_key] = colName ? formatCellValue(row[colName]) : ''
      }
      return result
    })
  }

  const handleComplete = () => {
    if (!invitationType) {
      alert('يرجى اختيار نوع الدعوات')
      return
    }

    const guestNameCol = columnMapping['guest.name']

    const guests = excelRows
      .filter((row) => {
        // Filter rows by the current batch ticket class (invitationType)
        const rowTicketClass = resolveTicketClass(row, invitationType)
        return rowTicketClass === invitationType
      })
      .map((row) => {
        const mapped: Record<string, any> & { guest_name: string; guest_count: number } = { 
          guest_name: resolveGuestName(row, guestNameCol),
          guest_count: resolveGuestCount(row)
        }
        
        // Map actual dynamic design fields
        for (const field of dynamicFields) {
          if (field.data_key !== 'guest.name') {
            const colName = columnMapping[field.data_key]
            mapped[field.data_key] = colName ? formatCellValue(row[colName]) : ''
          }
        }
        
        return { ...row, ...mapped }
      })

    onComplete({
      invitationType,
      templateId: selectedTemplateId,
      templateName: selectedTemplateName,
      guests,
      columnMapping,
    })
  }

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  // واجهة المستخدم
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  return (
    <div className="template-selection-flow">
      <div className="flow-header">
        <h2>🎯 إنشاء دعوات احترافية</h2>
        <p className="flow-subtitle">عملية احترافية وسلسة مع اختيار نوع الدعوات</p>
      </div>

      {/* Progress Bar - 5 خطوات */}
      <div className="flow-progress">
        <div className={`progress-step ${currentStep === 'type' ? 'active' : ['template', 'upload', 'mapping', 'preview'].includes(currentStep) ? 'completed' : ''}`}>
          <div className="step-number">1</div>
          <div className="step-label">النوع</div>
        </div>
        <div className="progress-line" />
        <div className={`progress-step ${currentStep === 'template' ? 'active' : ['upload', 'mapping', 'preview'].includes(currentStep) ? 'completed' : ''}`}>
          <div className="step-number">2</div>
          <div className="step-label">القالب</div>
        </div>
        <div className="progress-line" />
        <div className={`progress-step ${currentStep === 'upload' ? 'active' : ['mapping', 'preview'].includes(currentStep) ? 'completed' : ''}`}>
          <div className="step-number">3</div>
          <div className="step-label">الملف</div>
        </div>
        <div className="progress-line" />
        <div className={`progress-step ${currentStep === 'mapping' ? 'active' : currentStep === 'preview' ? 'completed' : ''}`}>
          <div className="step-number">4</div>
          <div className="step-label">البيانات</div>
        </div>
        <div className="progress-line" />
        <div className={`progress-step ${currentStep === 'preview' ? 'active' : ''}`}>
          <div className="step-number">5</div>
          <div className="step-label">معاينة</div>
        </div>
      </div>

      {/* Flow Content */}
      <div className="flow-content">
        {/* Step 0: Invitation Type Selection */}
        {currentStep === 'type' && (
          <div className="flow-step type-selection-step">
            <div className="step-title">اختر نوع الدعوات</div>
            <p className="step-description">حدد نوع الدعوات التي تريد إنشاءها</p>

            <div className="invitation-types-grid">
              {invitationTypes.map((type) => (
                <div
                  key={type.id}
                  className={`invitation-type-card ${invitationType === type.id ? 'selected' : ''}`}
                  onClick={() => handleTypeSelect(type.id)}
                >
                  <div className={`type-icon bg-gradient-to-br ${type.id === 'vip' ? 'from-yellow-400 to-yellow-600' : 'from-blue-400 to-blue-600'}`}>
                    {type.icon}
                  </div>
                  <h3 className="type-label">{type.label}</h3>
                  <p className="type-description">{type.description}</p>
                  {invitationType === type.id && (
                    <div className="selection-indicator">
                      <CheckCircle2 size={20} />
                    </div>
                  )}
                </div>
              ))}
            </div>

            <div className="step-actions">
              <button className="btn btn-secondary" onClick={onCancel}>
                إلغاء
              </button>
            </div>
          </div>
        )}

        {/* Step 1: Template Selection */}
        {currentStep === 'template' && (
          <div className="flow-step template-step">
            <div className="step-title">
              اختر القالب {invitationType === 'vip' ? '👑 (VIP)' : '👥 (عادي)'}
            </div>
            <p className="step-description">اختر القالب المناسب للدعوات</p>

            {templatesLoading ? (
              <div className="loading-state">
                <Loader2 size={32} className="spin" />
                <p>جاري تحميل القوالب...</p>
              </div>
            ) : templates.length === 0 ? (
              <div className="empty-state">
                <AlertCircle size={48} />
                <p>لا توجد قوالب متاحة لهذا النوع</p>
              </div>
            ) : (
              <div className="templates-grid">
                {templates.map((template) => (
                  <div
                    key={template.id}
                    className={`template-option ${selectedTemplateId === template.id ? 'selected' : ''}`}
                    onClick={() => handleTemplateSelect(template.id, template.name)}
                  >
                    {selectedTemplateId === template.id && <CheckCircle2 className="selection-indicator" size={24} />}
                    {(template as any).background_url && (
                      <img src={(template as any).background_url} alt={template.name} className="template-thumbnail" />
                    )}
                    <div className="template-info">
                      <div className="template-name">{template.name}</div>
                      <div className="template-type">
                        {(template as any).template_type === 'designed' ? '🎨 مصمم' : '⚡ سريع'}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div className="step-actions">
              <button className="btn btn-secondary" onClick={() => setCurrentStep('type')}>
                <ChevronLeft size={16} />
                رجوع
              </button>
              <button className="btn btn-primary" onClick={handleTemplateNext} disabled={!selectedTemplateId}>
                التالي
                <ChevronRight size={16} />
              </button>
            </div>
          </div>
        )}

        {/* Step 2: File Upload */}
        {currentStep === 'upload' && (
          <div className="flow-step upload-step">
            <div className="step-title">تحميل بيانات الضيوف</div>
            <p className="step-description">ملف Excel (.xlsx) يحتوي على بيانات الضيوف</p>

            <div className="file-upload-area">
              <input
                type="file"
                accept=".xlsx,.csv"
                onChange={handleFileSelect}
                disabled={isProcessing}
                id="file-input"
              />
              <label htmlFor="file-input" className={`upload-label ${uploadedFile ? 'has-file' : ''}`}>
                {isProcessing ? (
                  <>
                    <Loader2 size={32} className="spin" />
                    <p>جاري معالجة الملف...</p>
                  </>
                ) : uploadedFile ? (
                  <>
                    <CheckCircle2 size={32} />
                    <p>{uploadedFile.name}</p>
                    <span className="upload-hint">انقر لاختيار ملف آخر</span>
                  </>
                ) : (
                  <>
                    <Upload size={32} />
                    <p>اسحب الملف هنا أو انقر للاختيار</p>
                    <span className="upload-hint">ملفات Excel (.xlsx) أو CSV (.csv)</span>
                  </>
                )}
              </label>
            </div>

            {/* Show dynamic fields detected from the template */}
            {dynamicFields.length > 0 && (
              <div className="template-hint">
                <div className="hint-title">📋 الحقول المطلوبة من التصميم:</div>
                <table className="format-table">
                  <thead>
                    <tr>
                      <th>الحقل</th>
                      <th>المفتاح</th>
                      <th>مطلوب</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dynamicFields.map((field) => (
                      <tr key={field.data_key}>
                        <td>{field.label}</td>
                        <td style={{ direction: 'ltr', fontFamily: 'var(--font-en)', fontSize: 12, opacity: 0.7 }}>{field.data_key}</td>
                        <td>{field.required ? '✅ نعم' : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div className="step-actions">
              <button className="btn btn-secondary" onClick={() => setCurrentStep('template')}>
                <ChevronLeft size={16} />
                رجوع
              </button>
              <button className="btn btn-primary" onClick={() => setCurrentStep('mapping')} disabled={!uploadedFile}>
                التالي
                <ChevronRight size={16} />
              </button>
            </div>
          </div>
        )}

        {/* Step 3: Column Mapping — DYNAMIC */}
        {currentStep === 'mapping' && (
          <div className="flow-step mapping-step">
            <div className="step-title">تعيين الأعمدة</div>
            <p className="step-description">
              قم بربط حقول التصميم بأعمدة ملف الـ Excel المرفوع.
            </p>

            {mappingErrors.length > 0 && (
              <div className="error-box">
                {mappingErrors.map((error, i) => (
                  <div key={i} className="error-item">
                    <AlertCircle size={16} />
                    {error}
                  </div>
                ))}
              </div>
            )}

            <div className="mapping-step-content">
              {/* Form panel */}
              <div className="mapping-fields-panel">
                <div className="mapping-container-vertical">
                  {dynamicFields.map((field) => {
                    const isHovered = hoveredFieldKey === field.data_key
                    const mappedCol = columnMapping[field.data_key]
                    const sampleVal = mappedCol ? excelRows[0]?.[mappedCol] : null

                    return (
                      <div 
                        key={field.data_key} 
                        className={`mapping-item-card ${isHovered ? 'mapping-item-card--hovered' : ''} ${mappedCol ? 'mapping-item-card--mapped' : ''} ${field.required && !mappedCol ? 'mapping-item-card--required-error' : ''}`}
                        onMouseEnter={() => setHoveredFieldKey(field.data_key)}
                        onMouseLeave={() => setHoveredFieldKey(null)}
                      >
                        <div className="mapping-item-card-header">
                          <label className="mapping-item-card-label">
                            {field.label}
                            {field.required && <span className="mapping-item-badge mapping-item-badge--required">إلزامي للبطاقة</span>}
                            {!field.required && <span className="mapping-item-badge mapping-item-badge--optional">اختياري</span>}
                          </label>
                          {mappedCol && <CheckCircle2 size={15} className="check-icon" />}
                        </div>
                        <span className="mapping-item-card-key">مفتاح الربط: {field.data_key}</span>

                        <select
                          value={mappedCol || ''}
                          onChange={(e) => handleMappingChange(field.data_key, e.target.value)}
                          className="mapping-item-card-select"
                        >
                          <option value="">— اختر عمود البيانات —</option>
                          {excelColumns.map((col) => (
                            <option key={col.name} value={col.name}>
                              {col.name} {col.sampleValues[0] ? `(${col.sampleValues[0]})` : ''}
                            </option>
                          ))}
                        </select>

                        {sampleVal && (
                          <div className="mapping-item-card-preview">
                            <span className="preview-label-text">القيمة الأولى للمعاينة:</span>
                            <span className="preview-value-text">{sampleVal}</span>
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>

              {/* Live Preview panel */}
              <div className="mapping-preview-panel">
                <div className="preview-panel-title">معاينة بطاقة الدعوة التفاعلية</div>
                <div className="preview-panel-subtitle">مرر الماوس فوق أي حقل لرؤية موقعه على التصميم</div>

                {selectedTemplate && (
                  <div 
                    className="card-preview-container"
                    style={{
                      aspectRatio: selectedTemplate.orientation === 'landscape' || (selectedTemplate.width_px || 1080) > (selectedTemplate.height_px || 1920) 
                        ? '1.414 / 1' 
                        : '1 / 1.414',
                      backgroundColor: selectedTemplate.background_color || '#111827',
                      backgroundImage: selectedTemplate.background_url ? `url(${selectedTemplate.background_url})` : 'none',
                    }}
                  >
                    {/* Render design overlay elements */}
                    {templateElements
                      .filter(el => el.is_visible !== false)
                      .map((el) => {
                        const isDynamic = el.element_type === 'guest_name' || el.element_type === 'dynamic_text' || ['event_date', 'event_time', 'event_location', 'seat_number', 'gate', 'hall', 'table_number'].includes(el.element_type)
                        
                        const key = el.data_key || (el.element_type === 'guest_name' ? 'guest.name' : `custom.${el.element_type}`)
                        const mappedCol = columnMapping[key]
                        
                        let displayText = ''
                        if (el.element_type === 'qr_code' || el.element_type === 'barcode') {
                          displayText = el.element_type === 'qr_code' ? 'QR Code' : 'Barcode'
                        } else if (isDynamic) {
                          if (mappedCol) {
                            displayText = formatCellValue(excelRows[0]?.[mappedCol]) || el.label || key
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
                            className={`card-preview-element ${isDynamic ? 'card-preview-element--dynamic' : ''} ${mappedCol ? 'card-preview-element--mapped' : ''} ${isActive ? 'card-preview-element--active' : ''} ${el.element_type === 'qr_code' || el.element_type === 'barcode' ? 'card-preview-element--qr' : ''}`}
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
                              justifyContent: el.text_align === 'left' ? 'flex-start' : el.text_align === 'right' ? 'flex-end' : 'center',
                              textAlign: el.text_align as any || 'center',
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
                            {el.element_type === 'image' && (
                              <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }}>
                                {el.static_content ? (
                                  <img src={el.static_content} alt="Logo" style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }} />
                                ) : (
                                  <div style={{ fontSize: '9px', opacity: 0.6 }}>Image</div>
                                )}
                              </div>
                            )}
                            {el.element_type !== 'qr_code' && el.element_type !== 'barcode' && el.element_type !== 'image' && (
                              <span className="truncate-text">{displayText}</span>
                            )}
                          </div>
                        )
                      })}
                  </div>
                )}
              </div>
            </div>

            <div className="step-actions" style={{ marginTop: 24 }}>
              <button className="btn btn-secondary" onClick={() => setCurrentStep('upload')}>
                <ChevronLeft size={16} />
                رجوع
              </button>
              <button
                className="btn btn-primary"
                onClick={handleMappingNext}
                disabled={mappingErrors.length > 0}
              >
                معاينة النتائج
                <ChevronRight size={16} />
              </button>
            </div>
          </div>
        )}

        {/* Step 4: Preview with actual Excel data */}
        {currentStep === 'preview' && (
          <div className="flow-step preview-step">
            <div className="step-title">معاينة النتائج</div>
            <p className="step-description">تحقق من البيانات قبل إنشاء الدعوات ({excelRows.length} ضيف)</p>

            <div className="preview-container">
              <div className="preview-header">
                <div className="template-info">
                  <strong>القالب:</strong> {selectedTemplateName}
                </div>
                <div className="invitation-type-info">
                  <strong>النوع:</strong> {invitationType === 'vip' ? '👑 VIP' : '👥 عادي'}
                </div>
                <div className="guest-count">
                  <strong>عدد الضيوف:</strong> {excelRows.length}
                </div>
              </div>

              <div className="preview-table-wrapper">
                <table className="preview-table">
                  <thead>
                    <tr>
                      {dynamicFields.map((field) => (
                        <th key={field.data_key}>{field.label}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {getPreviewData().map((row, i) => (
                      <tr key={i}>
                        {dynamicFields.map((field) => (
                          <td key={field.data_key}>{row[field.data_key] || '—'}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {excelRows.length > 5 && (
                  <div className="more-rows-hint">
                    ... و {excelRows.length - 5} ضيف آخر
                  </div>
                )}
              </div>

              <div className="success-box">
                <CheckCircle2 size={20} />
                <span>جميع البيانات جاهزة للإنشاء</span>
              </div>
            </div>

            <div className="step-actions">
              <button className="btn btn-secondary" onClick={() => setCurrentStep('mapping')}>
                <ChevronLeft size={16} />
                رجوع
              </button>
              <button className="btn btn-primary btn-success" onClick={handleComplete}>
                <CheckCircle2 size={16} />
                إنشاء الدعوات
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
