export type SpreadsheetRow = Record<string, unknown>

export interface SpreadsheetSheet {
  name: string
  rows: SpreadsheetRow[]
  headers?: string[]
}

const MAX_IMPORT_BYTES = 5 * 1024 * 1024
const MAX_IMPORT_ROWS = 10_000
const MAX_IMPORT_COLUMNS = 100

async function createWorkbook() {
  const { Workbook } = await import('exceljs')
  return new Workbook()
}

function normalizeCellValue(value: unknown): unknown {
  if (value === null || value === undefined) return ''
  if (value instanceof Date || typeof value !== 'object') return value
  if ('result' in value) return normalizeCellValue((value as { result?: unknown }).result)
  if ('richText' in value) {
    const richText = (value as { richText?: Array<{ text?: string }> }).richText ?? []
    return richText.map((part) => part.text ?? '').join('')
  }
  if ('text' in value) return String((value as { text?: unknown }).text ?? '')
  return String(value)
}

function uniqueHeaders(values: unknown[]): string[] {
  const counts = new Map<string, number>()
  return values.map((value, index) => {
    const base = String(normalizeCellValue(value) ?? '').trim() || `column_${index + 1}`
    const occurrence = (counts.get(base) ?? 0) + 1
    counts.set(base, occurrence)
    return occurrence === 1 ? base : `${base}_${occurrence}`
  })
}

function parseCsv(content: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let value = ''
  let quoted = false

  for (let index = 0; index < content.length; index += 1) {
    const character = content[index]
    if (quoted) {
      if (character === '"' && content[index + 1] === '"') {
        value += '"'
        index += 1
      } else if (character === '"') {
        quoted = false
      } else {
        value += character
      }
      continue
    }
    if (character === '"') {
      quoted = true
    } else if (character === ',') {
      row.push(value)
      value = ''
    } else if (character === '\n' || character === '\r') {
      if (character === '\r' && content[index + 1] === '\n') index += 1
      row.push(value)
      if (row.some((cell) => cell.trim() !== '')) rows.push(row)
      row = []
      value = ''
    } else {
      value += character
    }
  }
  row.push(value)
  if (row.some((cell) => cell.trim() !== '')) rows.push(row)
  return rows
}

function validateImportFile(file: File): void {
  const fileName = file.name.toLowerCase()
  if (!fileName.endsWith('.xlsx') && !fileName.endsWith('.csv')) {
    throw new Error('يرجى اختيار ملف XLSX أو CSV')
  }
  if (file.size === 0) throw new Error('الملف فارغ')
  if (file.size > MAX_IMPORT_BYTES) {
    throw new Error('حجم الملف يتجاوز الحد الآمن البالغ 5 ميجابايت')
  }
}

function rowsToRecords(rawRows: unknown[][]): { headers: string[]; rows: SpreadsheetRow[] } {
  if (!rawRows.length) return { headers: [], rows: [] }
  const headers = uniqueHeaders(rawRows[0])
  if (headers.length > MAX_IMPORT_COLUMNS) {
    throw new Error(`عدد الأعمدة يتجاوز الحد الآمن (${MAX_IMPORT_COLUMNS})`)
  }
  const rows = rawRows.slice(1, MAX_IMPORT_ROWS + 1).reduce<SpreadsheetRow[]>((records, values) => {
    if (!values.some((value) => String(value ?? '').trim() !== '')) return records
    const record: SpreadsheetRow = {}
    headers.forEach((header, index) => {
      record[header] = normalizeCellValue(values[index])
    })
    records.push(record)
    return records
  }, [])
  if (rawRows.length - 1 > MAX_IMPORT_ROWS) {
    throw new Error(`عدد الصفوف يتجاوز الحد الآمن (${MAX_IMPORT_ROWS})`)
  }
  return { headers, rows }
}

async function loadSpreadsheet(file: File): Promise<{ headers: string[]; rows: SpreadsheetRow[] }> {
  validateImportFile(file)
  if (file.name.toLowerCase().endsWith('.csv')) {
    return rowsToRecords(parseCsv(await file.text()))
  }

  const workbook = await createWorkbook()
  await workbook.xlsx.load(await file.arrayBuffer())
  const worksheet = workbook.worksheets[0]
  if (!worksheet || worksheet.actualRowCount === 0) return { headers: [], rows: [] }
  if (worksheet.actualRowCount > MAX_IMPORT_ROWS + 1) {
    throw new Error(`عدد الصفوف يتجاوز الحد الآمن (${MAX_IMPORT_ROWS})`)
  }
  if (worksheet.actualColumnCount > MAX_IMPORT_COLUMNS) {
    throw new Error(`عدد الأعمدة يتجاوز الحد الآمن (${MAX_IMPORT_COLUMNS})`)
  }

  const rawRows: unknown[][] = []
  for (let rowNumber = 1; rowNumber <= worksheet.rowCount; rowNumber += 1) {
    const row = worksheet.getRow(rowNumber)
    const values: unknown[] = []
    for (let columnNumber = 1; columnNumber <= worksheet.actualColumnCount; columnNumber += 1) {
      values.push(normalizeCellValue(row.getCell(columnNumber).value))
    }
    if (values.some((value) => String(value ?? '').trim() !== '')) rawRows.push(values)
  }
  return rowsToRecords(rawRows)
}

function exportCellValue(value: unknown): string | number | boolean | Date | null {
  if (value === null || value === undefined) return null
  if (value instanceof Date || typeof value === 'number' || typeof value === 'boolean') return value
  const text = String(value)
  return /^[=+@-]/.test(text) ? `'${text}` : text
}

function safeSheetName(name: string, index: number): string {
  const normalized = name
    .replace(/[\\/:*?]/g, ' ')
    .replace(/\[/g, ' ')
    .replace(/\]/g, ' ')
    .trim()
    .slice(0, 31)
  return normalized || `Sheet ${index + 1}`
}

export async function readSpreadsheet(file: File): Promise<SpreadsheetRow[]> {
  return (await loadSpreadsheet(file)).rows
}

export async function readSpreadsheetHeaders(file: File): Promise<string[]> {
  return (await loadSpreadsheet(file)).headers
}

export async function downloadSpreadsheet(sheets: SpreadsheetSheet[], filename: string): Promise<void> {
  const workbook = await createWorkbook()
  sheets.forEach((sheet, index) => {
    const worksheet = workbook.addWorksheet(safeSheetName(sheet.name, index))
    const headers = sheet.headers ?? Array.from(new Set(sheet.rows.flatMap((row) => Object.keys(row))))
    worksheet.addRow(headers.map(exportCellValue))
    sheet.rows.forEach((row) => {
      worksheet.addRow(headers.map((header) => exportCellValue(row[header])))
    })
  })
  const content = await workbook.xlsx.writeBuffer()
  const blob = new Blob([content], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}
