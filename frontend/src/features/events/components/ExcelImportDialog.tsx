/**
 * ExcelImportDialog.tsx
 * واجهة احترافية وديناميكية لاستيراد ملفات Excel
 */

import { useState, useCallback } from 'react'
import { Upload, Download, X, AlertCircle, CheckCircle2, AlertTriangle, FileSpreadsheet, ChevronDown } from 'lucide-react'
import ExcelImportService, { ExcelImportResult, ColumnMapping } from '../services/ExcelImportService'
import '../styles/excel-import-dialog.css'
import { downloadGuestTemplate } from '../utils/guestTemplate'

interface ExcelImportDialogProps {
  eventId: string
  onImportComplete: (data: {
    invitations: Array<any>
    availableColumns: string[]
    columnMappings: ColumnMapping[]
  }) => void
  onClose: () => void
  remainingVip: number
  remainingNormal: number
}

export function ExcelImportDialog({
  eventId: _eventId,
  onImportComplete,
  onClose,
  remainingVip,
  remainingNormal
}: ExcelImportDialogProps) {
  const [stage, setStage] = useState<'upload' | 'preview' | 'confirm'>('upload')
  const [importResult, setImportResult] = useState<ExcelImportResult | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [fileName, setFileName] = useState('')
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set(['summary', 'columns']))

  // ═══════════════════════════════════════════════════════════════════════
  // Handlers
  // ═══════════════════════════════════════════════════════════════════════

  const handleFileSelect = useCallback(async (file: File | null) => {
    if (!file) return

    setIsLoading(true)
    setFileName(file.name)

    try {
      const result = await ExcelImportService.parseExcelFile(file)
      setImportResult(result)
      setStage('preview')
    } catch (error) {
      console.error('Failed to parse Excel file:', error)
      setImportResult({
        status: 'error',
        totalRows: 0,
        validRows: 0,
        invalidRows: 0,
        columnMappings: [],
        availableCustomColumns: [],
        parsedData: [],
        globalWarnings: [],
        globalErrors: ['خطأ غير متوقع في معالجة الملف'],
        statistics: {
          vipCount: 0,
          normalCount: 0,
          columnsDetected: 0,
          customFieldsCount: 0
        }
      })
      setStage('preview')
    } finally {
      setIsLoading(false)
    }
  }, [])

  const handleConfirmImport = useCallback(() => {
    if (!importResult || importResult.status === 'error') return

    const invitations = ExcelImportService.convertToInvitations(importResult)
    onImportComplete({
      invitations,
      availableColumns: importResult.availableCustomColumns,
      columnMappings: importResult.columnMappings
    })
  }, [importResult, onImportComplete])

  const downloadTemplate = async () => {
    await downloadGuestTemplate({ title: 'المناسبة' })
  }

  const toggleSection = (section: string) => {
    const newSections = new Set(expandedSections)
    if (newSections.has(section)) {
      newSections.delete(section)
    } else {
      newSections.add(section)
    }
    setExpandedSections(newSections)
  }

  // ═══════════════════════════════════════════════════════════════════════
  // Rendering Functions
  // ═══════════════════════════════════════════════════════════════════════

  const renderUploadStage = () => (
    <div className="excel-dialog__stage">
      <div className="excel-upload-box">
        <div className="excel-upload-box__icon">
          <FileSpreadsheet size={48} />
        </div>
        <h3>رفع ملف الضيوف</h3>
        <p>اختر ملف Excel يحتوي على بيانات الضيوف</p>

        <div className="excel-upload-actions">
          <label className="excel-upload-btn">
            <Upload size={18} />
            اختيار ملف Excel
            <input
              type="file"
              accept=".xlsx,.csv"
              onChange={(e) => handleFileSelect(e.target.files?.[0] ?? null)}
              disabled={isLoading}
              hidden
            />
          </label>
          <button className="excel-template-btn" onClick={() => { void downloadTemplate() }}>
            <Download size={18} />
            تنزيل النموذج
          </button>
        </div>

        <div className="excel-upload-hint">
          <div className="excel-hint-title">💡 نصائح للملف:</div>
          <ul className="excel-hint-list">
            <li><strong>العمود الإلزامي:</strong> اسم الضيف (لا يمكن تركه فارغاً)</li>
            <li><strong>أعمدة اختيارية:</strong> عدد الدعوات، نوع التذكرة</li>
            <li><strong>أعمدة إضافية:</strong> الهاتف، البريد، المقعد، وغيرها</li>
            <li><strong>الصيغة المدعومة:</strong> .xlsx و .csv فقط</li>
            <li><strong>الحد الأقصى:</strong> 10,000 صف</li>
          </ul>
        </div>
      </div>
    </div>
  )

  const renderPreviewStage = () => {
    if (!importResult) return null

    const isError = importResult.status === 'error'
    const isWarning = importResult.status === 'warning'
    const isSuccess = importResult.status === 'success'

    return (
      <div className="excel-dialog__stage">
        {/* Status Alert */}
        <div className={`excel-status-alert excel-status-alert--${importResult.status}`}>
          <div className="excel-status-alert__icon">
            {isSuccess && <CheckCircle2 size={24} />}
            {isWarning && <AlertTriangle size={24} />}
            {isError && <AlertCircle size={24} />}
          </div>
          <div className="excel-status-alert__content">
            <h4 className="excel-status-alert__title">
              {isSuccess && '✓ تم التحقق من الملف بنجاح'}
              {isWarning && '⚠ تم اكتشاف بعض التنبيهات'}
              {isError && '✗ خطأ: لا يمكن استخدام الملف'}
            </h4>
            <p className="excel-status-alert__desc">
              {fileName} • {(new Blob([fileName]).size / 1024).toFixed(1)} KB
            </p>
          </div>
        </div>

        {/* Error Messages */}
        {importResult.globalErrors.length > 0 && (
          <div className="excel-errors-box">
            <h5 className="excel-errors-box__title">❌ الأخطاء الحرجة:</h5>
            <div className="excel-errors-list">
              {importResult.globalErrors.map((error, i) => (
                <div key={i} className="excel-error-item">
                  <span className="excel-error-icon">✗</span>
                  <span className="excel-error-text">{error}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Summary Section */}
        <div className="excel-section">
          <button
            className="excel-section__header"
            onClick={() => toggleSection('summary')}
          >
            <span className="excel-section__title">📊 ملخص البيانات</span>
            <ChevronDown
              size={18}
              className={expandedSections.has('summary') ? 'rotated' : ''}
            />
          </button>

          {expandedSections.has('summary') && (
            <div className="excel-section__content">
              <div className="excel-stats-grid">
                <div className="excel-stat-card">
                  <div className="excel-stat-label">إجمالي الصفوف</div>
                  <div className="excel-stat-value">{importResult.totalRows}</div>
                </div>
                <div className="excel-stat-card excel-stat-card--success">
                  <div className="excel-stat-label">صفوف صحيحة</div>
                  <div className="excel-stat-value">{importResult.validRows}</div>
                </div>
                <div className={`excel-stat-card ${importResult.invalidRows > 0 ? 'excel-stat-card--warning' : ''}`}>
                  <div className="excel-stat-label">صفوف بها مشاكل</div>
                  <div className="excel-stat-value">{importResult.invalidRows}</div>
                </div>
                <div className="excel-stat-card">
                  <div className="excel-stat-label">أعمدة مكتشفة</div>
                  <div className="excel-stat-value">{importResult.statistics.columnsDetected}</div>
                </div>
              </div>

              <div className="excel-quota-check">
                <div className="excel-quota-item">
                  <span className="excel-quota-label">📍 دعوات VIP المخطط:</span>
                  <span className={`excel-quota-value ${importResult.statistics.vipCount > remainingVip ? 'excel-quota-value--error' : ''}`}>
                    {importResult.statistics.vipCount}
                  </span>
                  <span className="excel-quota-remaining">من {remainingVip} متاح</span>
                </div>
                <div className="excel-quota-item">
                  <span className="excel-quota-label">📍 دعوات عادية المخطط:</span>
                  <span className={`excel-quota-value ${importResult.statistics.normalCount > remainingNormal ? 'excel-quota-value--error' : ''}`}>
                    {importResult.statistics.normalCount}
                  </span>
                  <span className="excel-quota-remaining">من {remainingNormal} متاح</span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Columns Section */}
        <div className="excel-section">
          <button
            className="excel-section__header"
            onClick={() => toggleSection('columns')}
          >
            <span className="excel-section__title">🔍 الأعمدة المكتشفة</span>
            <ChevronDown
              size={18}
              className={expandedSections.has('columns') ? 'rotated' : ''}
            />
          </button>

          {expandedSections.has('columns') && (
            <div className="excel-section__content">
              <div className="excel-columns-list">
                {importResult.columnMappings.map((mapping, i) => (
                  <div key={i} className={`excel-column-item excel-column-item--${mapping.fieldType}`}>
                    <span className="excel-column-badge">
                      {mapping.fieldType === 'mandatory' && '🔴'}
                      {mapping.fieldType === 'optional-known' && '🟡'}
                      {mapping.fieldType === 'custom' && '🟢'}
                    </span>
                    <div className="excel-column-info">
                      <div className="excel-column-name">{mapping.columnName}</div>
                      <div className="excel-column-detect">{mapping.detectedAs}</div>
                    </div>
                    <div className={`excel-column-type ${mapping.fieldType}`}>
                      {mapping.fieldType === 'mandatory' && 'إلزامي'}
                      {mapping.fieldType === 'optional-known' && 'اختياري - معروف'}
                      {mapping.fieldType === 'custom' && 'إضافي'}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Warnings Section */}
        {importResult.globalWarnings.length > 0 && (
          <div className="excel-section">
            <button
              className="excel-section__header"
              onClick={() => toggleSection('warnings')}
            >
              <span className="excel-section__title">⚠️ التنبيهات ({importResult.globalWarnings.length})</span>
              <ChevronDown
                size={18}
                className={expandedSections.has('warnings') ? 'rotated' : ''}
              />
            </button>

            {expandedSections.has('warnings') && (
              <div className="excel-section__content">
                <div className="excel-warnings-list">
                  {importResult.globalWarnings.slice(0, 10).map((warning, i) => (
                    <div key={i} className="excel-warning-item">
                      <span className="excel-warning-icon">⚠</span>
                      <span className="excel-warning-text">{warning}</span>
                    </div>
                  ))}
                  {importResult.globalWarnings.length > 10 && (
                    <div className="excel-more-warnings">
                      +{importResult.globalWarnings.length - 10} تنبيهات إضافية
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Data Preview */}
        <div className="excel-section">
          <button
            className="excel-section__header"
            onClick={() => toggleSection('preview')}
          >
            <span className="excel-section__title">👁️ معاينة البيانات</span>
            <ChevronDown
              size={18}
              className={expandedSections.has('preview') ? 'rotated' : ''}
            />
          </button>

          {expandedSections.has('preview') && (
            <div className="excel-section__content">
              <div className="excel-preview-table">
                <table>
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>الاسم</th>
                      <th>العدد</th>
                      <th>النوع</th>
                      {importResult.availableCustomColumns.slice(0, 3).map(col => (
                        <th key={col} title={col}>{col.substring(0, 12)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {importResult.parsedData.slice(0, 5).map((row, i) => (
                      <tr key={i}>
                        <td>{i + 1}</td>
                        <td><strong>{row.guestName}</strong></td>
                        <td>{row.invitationCount}</td>
                        <td>
                          <span className={`excel-badge excel-badge--${row.ticketClass}`}>
                            {row.ticketClass === 'vip' ? 'VIP' : 'عادي'}
                          </span>
                        </td>
                        {importResult.availableCustomColumns.slice(0, 3).map(col => (
                          <td key={col} title={row.customFields[col]}>
                            {row.customFields[col]?.toString().substring(0, 10) || '-'}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {importResult.parsedData.length > 5 && (
                  <div className="excel-preview-more">
                    وعدد {importResult.parsedData.length - 5} صفوف إضافية...
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    )
  }

  // ═══════════════════════════════════════════════════════════════════════
  // Main Render
  // ═══════════════════════════════════════════════════════════════════════

  return (
    <div className="excel-dialog-overlay">
      <div className="excel-dialog">
        <div className="excel-dialog__header">
          <h2 className="excel-dialog__title">استيراد بيانات الضيوف من Excel</h2>
          <button
            className="excel-dialog__close"
            onClick={onClose}
            type="button"
          >
            <X size={20} />
          </button>
        </div>

        <div className="excel-dialog__content">
          {stage === 'upload' && renderUploadStage()}
          {stage === 'preview' && renderPreviewStage()}
        </div>

        <div className="excel-dialog__footer">
          {stage === 'preview' && (
            <>
              <button
                className="excel-dialog__btn excel-dialog__btn--secondary"
                onClick={() => {
                  setStage('upload')
                  setImportResult(null)
                  setFileName('')
                }}
              >
                اختيار ملف آخر
              </button>
              <button
                className="excel-dialog__btn excel-dialog__btn--primary"
                onClick={handleConfirmImport}
                disabled={importResult?.status === 'error' ||
                  !!(importResult && (importResult.statistics.vipCount > remainingVip ||
                   importResult.statistics.normalCount > remainingNormal))}
              >
                {isLoading ? 'جاري المعالجة...' : 'متابعة'}
              </button>
            </>
          )}
          {stage === 'upload' && (
            <button
              className="excel-dialog__btn excel-dialog__btn--secondary"
              onClick={onClose}
            >
              إغلاق
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export default ExcelImportDialog
