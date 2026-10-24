/**
 * ExcelImportService.ts
 * خدمة متقدمة لمعالجة استيراد ملفات Excel بشكل ديناميكي
 */

import { formatCellValue } from '../utils/mappingUtils'
import { readSpreadsheet } from '../utils/spreadsheet'

// ═══════════════════════════════════════════════════════════════════════
// Types & Interfaces
// ═══════════════════════════════════════════════════════════════════════

export interface ColumnMapping {
  columnIndex: number
  columnName: string
  fieldType: 'mandatory' | 'optional-known' | 'custom'
  mappedTo: string | null
  detectedAs: string | null
}

export interface ParsedRow {
  rowIndex: number
  guestName: string
  invitationCount: number
  ticketClass: 'vip' | 'normal'
  customFields: Record<string, any>
  warnings: string[]
  isValid: boolean
}

export interface ExcelImportResult {
  status: 'success' | 'warning' | 'error'
  totalRows: number
  validRows: number
  invalidRows: number
  columnMappings: ColumnMapping[]
  availableCustomColumns: string[]
  parsedData: ParsedRow[]
  globalWarnings: string[]
  globalErrors: string[]
  statistics: {
    vipCount: number
    normalCount: number
    columnsDetected: number
    customFieldsCount: number
  }
}

// ═══════════════════════════════════════════════════════════════════════
// Known Column Mappings (Multi-language)
// ═══════════════════════════════════════════════════════════════════════

const MANDATORY_COLUMNS = {
  guestName: [
    'اسم الضيف', 'اسم', 'الاسم الكامل', 'اسم الشخص',
    'guest_name', 'name', 'full_name', 'visitor_name', 'guest'
  ]
}

const OPTIONAL_KNOWN_COLUMNS = {
  invitationCount: [
    'عدد الأشخاص', 'عدد الاشخاص', 'عدد الدعوات', 'الكمية', 'العدد',
    'invitation_count', 'count', 'qty', 'quantity', 'number'
  ],
  ticketClass: [
    'نوع التذكرة', 'نوع الدخول', 'الفئة',
    'ticket_class', 'class', 'type', 'tier', 'category'
  ]
}

const CUSTOM_KNOWN_COLUMNS = {
  phone: ['رقم الهاتف', 'الهاتف', 'phone', 'tel', 'mobile', 'phone_number'],
  email: ['البريد الإلكتروني', 'البريد', 'email', 'e-mail', 'mail'],
  seat: ['رقم المقعد', 'المقعد', 'seat', 'seat_number', 'seat_no'],
  table: ['رقم الطاولة', 'الطاولة', 'table', 'table_number', 'table_no'],
  company: ['الشركة', 'company', 'organization', 'org'],
  title: ['الوظيفة', 'المنصب', 'title', 'position', 'job', 'job_title'],
  zone: ['منطقة', 'المنطقة', 'zone', 'area', 'section'],
  hall: ['قاعة', 'القاعة', 'hall', 'room', 'room_name'],
  notes: ['ملاحظات', 'notes', 'remarks', 'comments']
}

// ═══════════════════════════════════════════════════════════════════════
// Core Service Class
// ═══════════════════════════════════════════════════════════════════════

export class ExcelImportService {
  /**
   * تحليل ملف Excel بالكامل
   */
  static async parseExcelFile(file: File): Promise<ExcelImportResult> {
    const result: ExcelImportResult = {
      status: 'success',
      totalRows: 0,
      validRows: 0,
      invalidRows: 0,
      columnMappings: [],
      availableCustomColumns: [],
      parsedData: [],
      globalWarnings: [],
      globalErrors: [],
      statistics: {
        vipCount: 0,
        normalCount: 0,
        columnsDetected: 0,
        customFieldsCount: 0
      }
    }

    try {
      const rows = await readSpreadsheet(file)

      if (rows.length === 0) {
        result.status = 'error'
        result.globalErrors.push('لم يتم العثور على بيانات في الملف')
        return result
      }

      // ───────────────────────────────────────────────────────────────────
      // 1. كشف الأعمدة (Column Detection)
      // ───────────────────────────────────────────────────────────────────

      const firstRow = rows[0]
      const headerColumns = Object.keys(firstRow)
      result.statistics.columnsDetected = headerColumns.length

      const columnMappings = this._detectColumns(headerColumns)
      result.columnMappings = columnMappings

      // التحقق من العمود الإلزامي
      const guestNameMapping = columnMappings.find(m => m.fieldType === 'mandatory')
      if (!guestNameMapping) {
        result.status = 'error'
        result.globalErrors.push(
          `❌ العمود "اسم الضيف" غير موجود في الملف.\n` +
          `الأعمدة المتاحة: ${headerColumns.join(', ')}`
        )
        return result
      }

      const customColumns = columnMappings
        .filter(m => m.fieldType === 'custom')
        .map(m => m.columnName)
      result.availableCustomColumns = customColumns
      result.statistics.customFieldsCount = customColumns.length

      // ───────────────────────────────────────────────────────────────────
      // 2. معالجة الصفوف (Row Processing)
      // ───────────────────────────────────────────────────────────────────

      result.totalRows = rows.length
      const parsedRows: ParsedRow[] = []

      rows.forEach((row, index) => {
        const parsedRow = this._parseRow(row, columnMappings, index + 2)

        if (parsedRow.isValid) {
          result.validRows++
          parsedRows.push(parsedRow)

          // Update statistics
          if (parsedRow.ticketClass === 'vip') {
            result.statistics.vipCount += parsedRow.invitationCount
          } else {
            result.statistics.normalCount += parsedRow.invitationCount
          }
        } else {
          result.invalidRows++
        }

        // Add warnings if any
        parsedRow.warnings.forEach(w => {
          if (!result.globalWarnings.includes(w)) {
            result.globalWarnings.push(w)
          }
        })
      })

      result.parsedData = parsedRows

      // ───────────────────────────────────────────────────────────────────
      // 3. تحديد حالة النتيجة
      // ───────────────────────────────────────────────────────────────────

      if (result.invalidRows > 0) {
        result.status = 'warning'
      }

      if (result.validRows === 0) {
        result.status = 'error'
        result.globalErrors.push('لم يتم العثور على صفوف صحيحة في الملف')
      }

      return result
    } catch {
      return {
        ...result,
        status: 'error',
        globalErrors: ['تعذر قراءة الملف. تأكد من أنه XLSX أو CSV صالح ضمن الحد المسموح.']
      }
    }
  }

  /**
   * كشف الأعمدة ومطابقتها بالحقول المعروفة
   */
  private static _detectColumns(headers: string[]): ColumnMapping[] {
    const mappings: ColumnMapping[] = []
    const usedHeaders = new Set<string>()

    // 1. ابحث عن العمود الإلزامي
    const guestNameIndex = headers.findIndex(h =>
      MANDATORY_COLUMNS.guestName.some(name => this._normalizeString(h) === this._normalizeString(name))
    )

    if (guestNameIndex !== -1) {
      mappings.push({
        columnIndex: guestNameIndex,
        columnName: headers[guestNameIndex],
        fieldType: 'mandatory',
        mappedTo: 'guest_name',
        detectedAs: 'اسم الضيف'
      })
      usedHeaders.add(headers[guestNameIndex])
    }

    // 2. ابحث عن الأعمدة الاختيارية المعروفة
    const invCountIndex = headers.findIndex(h =>
      OPTIONAL_KNOWN_COLUMNS.invitationCount.some(name => this._normalizeString(h) === this._normalizeString(name))
    )
    if (invCountIndex !== -1) {
      mappings.push({
        columnIndex: invCountIndex,
        columnName: headers[invCountIndex],
        fieldType: 'optional-known',
        mappedTo: 'invitation_count',
        detectedAs: 'عدد الدعوات'
      })
      usedHeaders.add(headers[invCountIndex])
    }

    const ticketClassIndex = headers.findIndex(h =>
      OPTIONAL_KNOWN_COLUMNS.ticketClass.some(name => this._normalizeString(h) === this._normalizeString(name))
    )
    if (ticketClassIndex !== -1) {
      mappings.push({
        columnIndex: ticketClassIndex,
        columnName: headers[ticketClassIndex],
        fieldType: 'optional-known',
        mappedTo: 'ticket_class',
        detectedAs: 'نوع التذكرة'
      })
      usedHeaders.add(headers[ticketClassIndex])
    }

    // 3. ابحث عن الأعمدة الإضافية المعروفة
    for (const [customKey, aliases] of Object.entries(CUSTOM_KNOWN_COLUMNS)) {
      const index = headers.findIndex(h =>
        aliases.some(name => this._normalizeString(h) === this._normalizeString(name))
      )
      if (index !== -1 && !usedHeaders.has(headers[index])) {
        mappings.push({
          columnIndex: index,
          columnName: headers[index],
          fieldType: 'custom',
          mappedTo: customKey,
          detectedAs: this._getCustomFieldLabel(customKey)
        })
        usedHeaders.add(headers[index])
      }
    }

    // 4. أضف الأعمدة المتبقية كـ custom fields
    headers.forEach((header, index) => {
      if (!usedHeaders.has(header)) {
        mappings.push({
          columnIndex: index,
          columnName: header,
          fieldType: 'custom',
          mappedTo: this._slugify(header),
          detectedAs: header
        })
      }
    })

    return mappings
  }

  /**
   * معالجة صف واحد من البيانات
   */
  private static _parseRow(row: Record<string, unknown>, mappings: ColumnMapping[], rowIndex: number): ParsedRow {
    const warnings: string[] = []
    const customFields: Record<string, any> = {}

    // استخرج البيانات من الصف
    const guestNameMapping = mappings.find(m => m.fieldType === 'mandatory')!
    const guestName = String(row[guestNameMapping.columnName] ?? '').trim()

    if (!guestName) {
      return {
        rowIndex,
        guestName: '',
        invitationCount: 0,
        ticketClass: 'normal',
        customFields: {},
        warnings: [`السطر ${rowIndex}: اسم الضيف مفقود`],
        isValid: false
      }
    }

    // عدد الدعوات
    const invCountMapping = mappings.find(m => m.mappedTo === 'invitation_count')
    let invitationCount = 1
    if (invCountMapping) {
      const rawValue = row[invCountMapping.columnName]
      const parsed = Number(rawValue)
      if (Number.isFinite(parsed) && parsed >= 1 && parsed <= 100) {
        invitationCount = Math.floor(parsed)
      } else if (rawValue !== '' && rawValue !== null) {
        warnings.push(`السطر ${rowIndex}: عدد الدعوات "${rawValue}" غير صحيح → سيتم استخدام 1`)
        invitationCount = 1
      }
    }

    // نوع التذكرة
    const ticketClassMapping = mappings.find(m => m.mappedTo === 'ticket_class')
    let ticketClass: 'vip' | 'normal' = 'normal'
    if (ticketClassMapping) {
      const rawValue = String(row[ticketClassMapping.columnName] ?? '').trim().toLowerCase()
      if (['vip', 'v', 'كبار الشخصيات'].includes(rawValue)) {
        ticketClass = 'vip'
      } else if (rawValue && rawValue !== '') {
        warnings.push(
          `السطر ${rowIndex}: نوع التذكرة "${rawValue}" غير واضح → سيتم استخدام "عادي"`
        )
      }
    }

    // البيانات الإضافية
    mappings
      .filter(m => m.fieldType === 'custom')
      .forEach(mapping => {
        const value = row[mapping.columnName]
        if (value !== '' && value !== null && value !== undefined) {
          customFields[mapping.mappedTo!] = formatCellValue(value)
        }
      })

    return {
      rowIndex,
      guestName,
      invitationCount,
      ticketClass,
      customFields,
      warnings,
      isValid: true
    }
  }

  /**
   * تطبيع النصوص للمقارنة
   */
  private static _normalizeString(str: string): string {
    return str
      .toLowerCase()
      .trim()
      .replace(/\s+/g, ' ')
      .replace(/[^\w؀-ۿ\s]/g, '')
  }

  /**
   * تحويل الاسم إلى slug
   */
  private static _slugify(str: string): string {
    return str
      .toLowerCase()
      .trim()
      .replace(/\s+/g, '_')
      .replace(/[^\w؀-ۿ_]/g, '')
  }

  /**
   * الحصول على تسمية الحقل الإضافي
   */
  private static _getCustomFieldLabel(key: string): string {
    const labels: Record<string, string> = {
      phone: 'رقم الهاتف',
      email: 'البريد الإلكتروني',
      seat: 'رقم المقعد',
      table: 'رقم الطاولة',
      company: 'الشركة',
      title: 'الوظيفة',
      zone: 'المنطقة',
      hall: 'القاعة',
      notes: 'ملاحظات'
    }
    return labels[key] || key
  }

  /**
   * تحويل النتائج إلى صيغة للإرسال للـ API
   */
  static convertToInvitations(
    result: ExcelImportResult
  ): Array<{
    guest_name: string
    ticket_class: 'vip' | 'normal'
    custom_fields?: Record<string, any>
  }> {
    const invitations: Array<any> = []

    result.parsedData.forEach(row => {
      for (let i = 0; i < row.invitationCount; i++) {
        invitations.push({
          guest_name: row.guestName,
          ticket_class: row.ticketClass,
          custom_fields: Object.keys(row.customFields).length > 0 ? row.customFields : undefined
        })
      }
    })

    return invitations
  }
}

export default ExcelImportService
