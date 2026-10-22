/**
 * mappingUtils.ts — أدوات تعيين وقراءة الحقول لملفات إكسل والقوالب
 */

export const getCleanFieldLabel = (dataKey: string, elType: string, label?: string | null): string => {
  const defaultLabels: Record<string, string> = {
    'guest.name': 'اسم الضيف',
    'guest_name': 'اسم الضيف',
    'event_date': 'تاريخ الفعالية',
    'event_time': 'وقت الفعالية',
    'event_location': 'مكان الفعالية',
    'seat_number': 'رقم المقعد',
    'gate': 'البوابة',
    'hall': 'القاعة',
    'table_number': 'رقم الطاولة',
    'qr_code': 'رمز الدخول QR',
    'barcode': 'رمز الباركود'
  }

  // If label is custom and not generic, use it
  if (label && !label.startsWith('نص ديناميكي') && !label.startsWith('بيانات متغيرة') && !label.startsWith('dynamic_text')) {
    return label
  }

  // Fallback to default element type labels
  if (defaultLabels[elType]) {
    return defaultLabels[elType]
  }
  if (defaultLabels[dataKey]) {
    return defaultLabels[dataKey]
  }

  // Translate common english keys to Arabic
  if (dataKey && !dataKey.startsWith('نص ديناميكي') && !dataKey.startsWith('بيانات متغيرة') && !dataKey.startsWith('dynamic_text')) {
    const cleanKey = dataKey.includes('.') ? dataKey.split('.').pop() || dataKey : dataKey
    const translations: Record<string, string> = {
      name: 'الاسم',
      date: 'التاريخ',
      time: 'الوقت',
      location: 'الموقع',
      seat: 'المقعد',
      table: 'الطاولة',
      gate: 'البوابة',
      hall: 'القاعة',
      phone: 'رقم الجوال',
      email: 'البريد الإلكتروني',
      company: 'الجهة/الشركة',
      position: 'المسمى الوظيفي',
      notes: 'ملاحظات',
      day: 'اليوم'
    }
    return translations[cleanKey.toLowerCase()] || dataKey
  }

  return label || dataKey || 'بيانات متغيرة'
}

export const findStandardColumn = (row: any, aliases: string[]): string | null => {
  if (!row || typeof row !== 'object') return null
  const keys = Object.keys(row)
  
  // Try exact match first (case-insensitive, trimmed)
  const normalizedAliases = aliases.map(a => a.toLowerCase().trim())
  for (const key of keys) {
    const keyLower = key.toLowerCase().trim()
    if (normalizedAliases.includes(keyLower)) {
      return key
    }
  }

  // Try substring match next
  for (const key of keys) {
    const keyLower = key.toLowerCase().trim()
    if (normalizedAliases.some(alias => keyLower.includes(alias) || alias.includes(keyLower))) {
      return key
    }
  }

  return null
}

const sanitizeArabicDigits = (val: any): string => {
  return String(val ?? '').replace(/[٠-٩]/g, (c) => String(c.charCodeAt(0) - 0x0660)).replace(/[۰-۹]/g, (c) => String(c.charCodeAt(0) - 0x06f0))
}

export const resolveGuestName = (row: any, mappedCol?: string | null): string => {
  if (mappedCol && row[mappedCol]) {
    return String(row[mappedCol]).trim().replace(/\s+/g, ' ')
  }
  
  const aliases = ['اسم الضيف', 'guest_name', 'name', 'اسم', 'الاسم', 'guestname', 'الضيف', 'الاسم الكريم']
  const matchedCol = findStandardColumn(row, aliases)
  if (matchedCol && row[matchedCol]) {
    return String(row[matchedCol]).trim().replace(/\s+/g, ' ')
  }
  
  throw new Error('اسم الضيف مطلوب لكل صف في الملف.')
}

export const resolveGuestCount = (row: any): number => {
  const aliases = ['عدد الأشخاص', 'عدد الاشخاص', 'عدد الدعوات', 'العدد', 'عدد', 'guest_count', 'invitation_count', 'count']
  const matchedCol = findStandardColumn(row, aliases)
  if (matchedCol && row[matchedCol]) {
    const parsed = Number(sanitizeArabicDigits(row[matchedCol]))
    if (Number.isInteger(parsed) && parsed >= 1 && parsed <= 100) return parsed
    throw new Error('عدد الأشخاص يجب أن يكون عددًا صحيحًا من 1 إلى 100.')
  }
  return 1
}

export const resolveTicketClass = (row: any, defaultClass: 'vip' | 'normal'): 'vip' | 'normal' => {
  const aliases = ['نوع التذكرة', 'نوع التذكره', 'النوع', 'الفئة', 'الفئه', 'ticket_class', 'class', 'type']
  const matchedCol = findStandardColumn(row, aliases)
  if (matchedCol && row[matchedCol]) {
    const val = String(row[matchedCol]).toLowerCase().trim()
    if (val.includes('vip') || val.includes('هام') || val.includes('مهم') || val.includes('خاص') || val.includes('👑')) {
      return 'vip'
    }
    if (val.includes('normal') || val.includes('عادي') || val.includes('👥') || val.includes('عام')) {
      return 'normal'
    }
  }
  if (matchedCol && String(row[matchedCol] ?? '').trim()) throw new Error('فئة التذكرة غير صالحة. استخدم عادي أو VIP.')
  return defaultClass
}

export const formatCellValue = (value: any): any => {
  if (value === null || value === undefined) return ''
  if (value instanceof Date) {
    if (!isNaN(value.getTime())) {
      const y = value.getFullYear()
      const m = String(value.getMonth() + 1).padStart(2, '0')
      const d = String(value.getDate()).padStart(2, '0')
      return `${y}-${m}-${d}`
    }
  }
  if (typeof value === 'string') {
    // If it's an ISO date string
    const isoMatch = value.match(/^(\d{4})-(\d{2})-(\d{2})T/)
    if (isoMatch) {
      return `${isoMatch[1]}-${isoMatch[2]}-${isoMatch[3]}`
    }
  }
  return value
}
