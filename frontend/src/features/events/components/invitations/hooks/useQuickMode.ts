/**
 * useQuickMode.ts
 * Business logic for Quick Generation mode (barcode-only).
 * Handles: manual guest entry, count-based generation, Excel import,
 * RSVP validation, and generation trigger.
 */
import type { InvitationStateReturn } from './useInvitationState'
import type { FastInvitationItem } from '../../../api/invitationsApi'
import {
  isPhoneField,
  isEmailField,
  parseTicketClass,
  RESERVED_FIELD_NAMES,
  CORE_EXCEL_COLUMNS,
} from '../types'
import { formatCellValue } from '../../../utils/mappingUtils'
import { EventModel } from '../../../types'
import { downloadSpreadsheet, readSpreadsheet } from '../../../utils/spreadsheet'

export function useQuickMode(state: InvitationStateReturn, event: EventModel) {
  const {
    quickManualGuests, setQuickManualGuests,
    quickFormName, setQuickFormName,
    quickFormCount, setQuickFormCount,
    quickFormClass,
    quickDynamicFields, setQuickDynamicFields,
    newQuickFieldName, setNewQuickFieldName,
    quickFormPhone, setQuickFormPhone,
    quickFormEmail, setQuickFormEmail,
    quickFormCustomFields, setQuickFormCustomFields,
    excelImportedGuests, setExcelImportedGuests,
    setExcelImportFileName,
    setExcelImportErrors,
    setLocalError,
    requireRsvp,
    quickInputMode, setQuickInputMode,
    generationSource, setGenerationSource,
    vipCount, normalCount,
    guestPrefix,
    layout,
    canExport,
    generate,
    singleGuestName, setSingleGuestName,
    singleGuestCount, setSingleGuestCount,
    singleGuestClass, setSingleGuestClass,
    setShowSingleGuestModal,
  } = state

  // ═══════════════════════════════════════════════════════════
  // Quick Manual Guests
  // ═══════════════════════════════════════════════════════════

  const addQuickManualGuest = () => {
    const name = quickFormName.trim()
    if (!name) {
      setLocalError('يرجى كتابة اسم الضيف')
      return
    }
    if (name.length > 200 || !Number.isInteger(quickFormCount) || quickFormCount < 1 || quickFormCount > 100) {
      setLocalError('اسم الضيف بحد أقصى 200 حرف، وعدد الأشخاص عدد صحيح من 1 إلى 100.')
      return
    }
    if (requireRsvp) {
      const phone = quickFormPhone.trim()
      const email = quickFormEmail.trim()
      if (!phone && !email) {
        setLocalError('يجب إدخال رقم الجوال أو البريد الإلكتروني للضيف لتفعيل تأكيد الحضور.')
        return
      }
    }

    const customFields: Record<string, string> = {}
    quickDynamicFields.forEach((field) => {
      customFields[field] = quickFormCustomFields[field] || ''
    })

    if (requireRsvp || quickFormPhone.trim()) {
      customFields['رقم الجوال'] = quickFormPhone.trim()
    }
    if (requireRsvp || quickFormEmail.trim()) {
      customFields['البريد الإلكتروني'] = quickFormEmail.trim()
    }

    setQuickManualGuests((prev) => [
      ...prev,
      {
        guest_name: name,
        invitation_count: quickFormCount,
        ticket_class: quickFormClass,
        custom_fields: customFields,
      },
    ])
    setQuickFormName('')
    setQuickFormPhone('')
    setQuickFormEmail('')
    setQuickFormCount(1)
    setQuickFormCustomFields({})
    setLocalError(null)
  }

  const deleteQuickManualGuest = (index: number) => {
    setQuickManualGuests((prev) => prev.filter((_, i) => i !== index))
  }

  const handleAddQuickField = () => {
    const fieldName = newQuickFieldName.trim()
    if (!fieldName) return
    if (RESERVED_FIELD_NAMES.includes(fieldName)) {
      setLocalError('هذا الاسم محجوز كحقل أساسي')
      return
    }
    if (quickDynamicFields.includes(fieldName)) {
      setLocalError('الحقل موجود بالفعل')
      return
    }
    setQuickDynamicFields((prev) => [...prev, fieldName])
    setNewQuickFieldName('')
    setLocalError(null)
  }

  const removeQuickDynamicField = (fieldName: string) => {
    setQuickDynamicFields((prev) => prev.filter((f) => f !== fieldName))
    setQuickManualGuests((prev) => prev.map((g) => {
      if (!g.custom_fields) return g
      const updated = { ...g.custom_fields }
      delete updated[fieldName]
      return { ...g, custom_fields: updated }
    }))
  }

  // ═══════════════════════════════════════════════════════════
  // Single Guest Add
  // ═══════════════════════════════════════════════════════════

  const addSingleGuest = () => {
    const guestName = singleGuestName.trim()
    if (!guestName) {
      setLocalError('اكتب اسم الشخص أولاً')
      return
    }
    if (!Number.isInteger(singleGuestCount) || singleGuestCount < 1 || singleGuestCount > 100) {
      setLocalError('عدد الأشخاص يجب أن يكون عددًا صحيحًا من 1 إلى 100')
      return
    }

    setExcelImportedGuests((prev) => [
      ...prev,
      {
        guest_name: guestName,
        invitation_count: singleGuestCount,
        ticket_class: singleGuestClass,
      },
    ])
    setExcelImportErrors([])
    setExcelImportFileName((prev) => prev || 'دعوات مضافة يدويًا')
    setGenerationSource('quick')
    setQuickInputMode('excel')
    setSingleGuestName('')
    setSingleGuestCount(1)
    setSingleGuestClass('normal')
    setLocalError(null)
    setShowSingleGuestModal(false)
  }

  // ═══════════════════════════════════════════════════════════
  // Excel File Handling
  // ═══════════════════════════════════════════════════════════

  const handleGuestFileSelected = async (file: File | null, target: 'excel' | 'design') => {
    if (!file) return
    setLocalError(null)
    if (target === 'excel') {
      setExcelImportErrors([])
    }

    try {
      const rows = await readSpreadsheet(file)

      const parsedRows: typeof excelImportedGuests = []
      const errors: string[] = []

      rows.forEach((row, index) => {
        const guestName = String(row['اسم الضيف'] ?? row['guest_name'] ?? row['name'] ?? '').trim()
        const invitationCountRaw = row['عدد الأشخاص'] ?? row['عدد الدعوات'] ?? row['invitation_count'] ?? row['count'] ?? 1
        const invitationCount = Number(String(invitationCountRaw).replace(/[٠-٩۰-۹]/g, c => String(c.charCodeAt(0) >= 0x06f0 ? c.charCodeAt(0) - 0x06f0 : c.charCodeAt(0) - 0x0660)))
        const ticketClass = parseTicketClass(row['نوع التذكرة'] ?? row['ticket_class'] ?? row['class'])

        // Collect custom fields
        const custom_fields: Record<string, string> = {}
        for (const [key, value] of Object.entries(row)) {
          if (!CORE_EXCEL_COLUMNS.includes(key)) {
            if (value !== undefined && value !== null && value !== '') {
              custom_fields[key] = String(formatCellValue(value))
            }
          }
        }

        if (!guestName) {
          errors.push(`السطر ${index + 2}: اسم الضيف مفقود`)
          return
        }
        if (!Number.isInteger(invitationCount) || invitationCount < 1 || invitationCount > 100) {
          errors.push(`السطر ${index + 2}: عدد الأشخاص يجب أن يكون عددًا صحيحًا بين 1 و100`)
          return
        }

        parsedRows.push({
          guest_name: guestName,
          invitation_count: invitationCount,
          ticket_class: ticketClass,
          custom_fields,
        })
      })

      if (!parsedRows.length) {
        if (target === 'excel') {
          setExcelImportErrors(errors.length ? errors : ['لم يتم العثور على صفوف صالحة داخل الملف'])
          setExcelImportedGuests([])
          setExcelImportFileName(file.name)
        }
        return
      }

      if (target === 'excel') {
        setExcelImportedGuests(parsedRows)
        setExcelImportFileName(file.name)
        setExcelImportErrors(errors)
        if (generationSource !== 'design') {
          setGenerationSource('quick')
          setQuickInputMode('excel')
        }
      }
    } catch {
      if (target === 'excel') {
        setExcelImportedGuests([])
        setExcelImportFileName(file.name)
        setExcelImportErrors(['تعذر قراءة الملف. استخدم ملف XLSX أو CSV'])
      }
    }
  }

  const clearImportedGuests = () => {
    setExcelImportedGuests([])
    setExcelImportFileName('')
    setExcelImportErrors([])
  }

  // ═══════════════════════════════════════════════════════════
  // Excel Template Download
  // ═══════════════════════════════════════════════════════════

  const downloadQuickExcelTemplate = async () => {
    const headers = ['اسم الضيف', 'عدد الأشخاص', 'نوع التذكرة']
    if (requireRsvp) {
      headers.push('رقم الجوال', 'البريد الإلكتروني')
    }

    const expectedRows = quickInputMode === 'names'
      ? quickManualGuests.length
      : quickInputMode === 'excel'
      ? excelImportedGuests.length
      : (vipCount + normalCount)

    const rowsCount = expectedRows > 0 ? expectedRows : 5
    const templateRows: any[] = []

    if (quickInputMode === 'names' && quickManualGuests.length > 0) {
      quickManualGuests.forEach((guest) => {
        const row: Record<string, any> = {
          'اسم الضيف': guest.guest_name,
          'عدد الأشخاص': guest.invitation_count,
          'نوع التذكرة': guest.ticket_class === 'vip' ? 'VIP' : 'normal'
        }
        if (requireRsvp) {
          const fields = guest.custom_fields || {}
          const existingPhoneKey = Object.keys(fields).find(k => isPhoneField(k))
          const existingEmailKey = Object.keys(fields).find(k => isEmailField(k))
          row['رقم الجوال'] = existingPhoneKey ? fields[existingPhoneKey] : ''
          row['البريد الإلكتروني'] = existingEmailKey ? fields[existingEmailKey] : ''
        }
        templateRows.push(row)
      })
    } else if (quickInputMode === 'excel' && excelImportedGuests.length > 0) {
      excelImportedGuests.forEach((guest) => {
        const row: Record<string, any> = {
          'اسم الضيف': guest.guest_name,
          'عدد الأشخاص': guest.invitation_count,
          'نوع التذكرة': guest.ticket_class === 'vip' ? 'VIP' : 'normal'
        }
        if (requireRsvp) {
          const fields = guest.custom_fields || {}
          const existingPhoneKey = Object.keys(fields).find(k => isPhoneField(k))
          const existingEmailKey = Object.keys(fields).find(k => isEmailField(k))
          row['رقم الجوال'] = existingPhoneKey ? fields[existingPhoneKey] : ''
          row['البريد الإلكتروني'] = existingEmailKey ? fields[existingEmailKey] : ''
        }
        templateRows.push(row)
      })
    } else {
      for (let i = 0; i < vipCount; i++) {
        const row: Record<string, any> = {
          'اسم الضيف': `ضيف VIP ${i + 1}`,
          'عدد الأشخاص': 1,
          'نوع التذكرة': 'VIP'
        }
        if (requireRsvp) {
          row['رقم الجوال'] = ''
          row['البريد الإلكتروني'] = ''
        }
        templateRows.push(row)
      }
      for (let i = 0; i < normalCount; i++) {
        const row: Record<string, any> = {
          'اسم الضيف': `ضيف ${i + 1}`,
          'عدد الأشخاص': 1,
          'نوع التذكرة': 'normal'
        }
        if (requireRsvp) {
          row['رقم الجوال'] = ''
          row['البريد الإلكتروني'] = ''
        }
        templateRows.push(row)
      }
      if (templateRows.length === 0) {
        for (let i = 0; i < rowsCount; i++) {
          const row: Record<string, any> = {
            'اسم الضيف': `ضيف ${i + 1}`,
            'عدد الأشخاص': 1,
            'نوع التذكرة': 'normal'
          }
          if (requireRsvp) {
            row['رقم الجوال'] = ''
            row['البريد الإلكتروني'] = ''
          }
          templateRows.push(row)
        }
      }
    }

    await downloadSpreadsheet([
      { name: 'Guests', rows: templateRows, headers },
      {
        name: 'Guide',
        rows: [
          { 'الحقل': 'اسم الضيف', 'الوصف': 'اسم الضيف أو الجهة المدعوة', 'مطلوب': 'نعم', 'مثال': 'أحمد محمد' },
          { 'الحقل': 'عدد الأشخاص', 'الوصف': 'عدد الأشخاص شاملًا الضيف؛ يصدر رمز دخول واحد للمجموعة', 'مطلوب': 'لا (الافتراضي 1)', 'مثال': '2' },
          { 'الحقل': 'نوع التذكرة', 'الوصف': 'vip أو normal', 'مطلوب': 'لا (الافتراضي normal)', 'مثال': 'vip' },
          ...(requireRsvp ? [
            { 'الحقل': 'رقم الجوال', 'الوصف': 'رقم هاتف الضيف لإرسال الدعوة وطلب تأكيد الحضور', 'مطلوب': 'نعم (أو البريد)', 'مثال': '+967700000000' },
            { 'الحقل': 'البريد الإلكتروني', 'الوصف': 'البريد الإلكتروني لإرسال الدعوة وطلب تأكيد الحضور', 'مطلوب': 'نعم (أو الجوال)', 'مثال': 'ahmed@example.com' }
          ] : [])
        ]
      }
    ], `guest-import-template-${event.id.slice(0, 8)}.xlsx`)
  }

  // ═══════════════════════════════════════════════════════════
  // Generate (Quick)
  // ═══════════════════════════════════════════════════════════

  const handleGenerate = () => {
    if (generationSource !== 'quick') return
    if (quickInputMode === 'excel' && excelImportedGuests.length === 0) return
    if (quickInputMode === 'names' && quickManualGuests.length === 0) return
    if (quickInputMode === 'manual' && vipCount === 0 && normalCount === 0) return

    setLocalError(null)
    const size = quickInputMode === 'names' ? quickManualGuests.length : quickInputMode === 'excel' ? excelImportedGuests.length : vipCount + normalCount
    if (size > 1000 || (quickInputMode === 'excel' && (state.excelImportErrors?.length || 0) > 0)) {
      setLocalError('الحد الحالي 1000 بطاقة للعملية. أصلح أخطاء الملف قبل الإنشاء.')
      return
    }

    // RSVP validation
    if (requireRsvp) {
      if (quickInputMode === 'manual') {
        setLocalError('لا يمكن تفعيل تأكيد الحضور عند الإنشاء بالعدد لعدم وجود بيانات اتصال للضيوف.')
        return
      }
      if (quickInputMode === 'names') {
        const invalidGuests = quickManualGuests.filter(g => {
          const fields = g.custom_fields || {}
          const hasPhone = Object.keys(fields).some(k => isPhoneField(k) && (fields[k] || '').trim())
          const hasEmail = Object.keys(fields).some(k => isEmailField(k) && (fields[k] || '').trim())
          return !hasPhone && !hasEmail
        })
        if (invalidGuests.length > 0) {
          const names = invalidGuests.map(g => g.guest_name).join('، ')
          setLocalError(`الضيوف التاليين يفتقرون لبيانات الاتصال (الهاتف أو البريد الإلكتروني): ${names}`)
          return
        }
      }
      if (quickInputMode === 'excel') {
        const allCustomKeys = new Set<string>()
        excelImportedGuests.forEach(g => {
          Object.keys(g.custom_fields || {}).forEach(k => allCustomKeys.add(k))
        })
        const customKeysArray = Array.from(allCustomKeys)
        const hasContactField = customKeysArray.some(field => isPhoneField(field) || isEmailField(field))
        if (!hasContactField) {
          setLocalError('يجب أن يحتوي ملف Excel على عمود لرقم الهاتف (مثل: الجوال، الهاتف) أو البريد الإلكتروني لتفعيل تأكيد الحضور.')
          return
        }
        const emptyRows: number[] = []
        excelImportedGuests.forEach((g, index) => {
          const fields = g.custom_fields || {}
          const hasPhone = Object.keys(fields).some(k => isPhoneField(k) && (fields[k] || '').trim())
          const hasEmail = Object.keys(fields).some(k => isEmailField(k) && (fields[k] || '').trim())
          if (!hasPhone && !hasEmail) {
            emptyRows.push(index + 2)
          }
        })
        if (emptyRows.length > 0) {
          setLocalError(`الصفوف التالية في ملف Excel تفتقر لبيانات الاتصال (رقم الهاتف أو البريد الإلكتروني): ${emptyRows.join(', ')}`)
          return
        }
      }
    }

    // Build invitations array
    const invitations: FastInvitationItem[] = []
    if (quickInputMode === 'excel') {
      excelImportedGuests.forEach((guest) => {
        invitations.push({
          guest_name: guest.guest_name,
          ticket_class: guest.ticket_class,
          guest_count: guest.invitation_count,
          metadata: { require_rsvp: requireRsvp, custom_fields: guest.custom_fields || {} },
        })
      })
    } else if (quickInputMode === 'names') {
      quickManualGuests.forEach((guest) => {
        invitations.push({
          guest_name: guest.guest_name,
          ticket_class: guest.ticket_class,
          guest_count: guest.invitation_count,
          metadata: { require_rsvp: requireRsvp, custom_fields: guest.custom_fields || {} },
        })
      })
    } else {
      for (let i = 0; i < vipCount; i++)
        invitations.push({
          guest_name: `${guestPrefix} VIP ${i + 1}`,
          ticket_class: 'vip' as const,
          metadata: { require_rsvp: requireRsvp },
        })
      for (let i = 0; i < normalCount; i++)
        invitations.push({
          guest_name: `${guestPrefix} ${i + 1}`,
          ticket_class: 'normal' as const,
          metadata: { require_rsvp: requireRsvp },
        })
    }

    generate(
      {
        event_id: event.id,
        invitations,
        source_kind: quickInputMode === 'excel' ? 'excel' : quickInputMode === 'names' ? 'names' : 'count',
        count: { vip_count: vipCount, normal_count: normalCount, guest_name_prefix: guestPrefix },
        original_filename: quickInputMode === 'excel' ? state.excelImportFileName || undefined : undefined,
        generate_pdf: canExport !== false,
        generate_zip: canExport !== false,
        upload_individual_barcodes: false,
        layout_config: {
          ...layout,
          show_code_text: false,
          show_guest_name: false,
        },
      },
      { onError: (err: any) => setLocalError(err) },
    )
  }

  return {
    addQuickManualGuest,
    deleteQuickManualGuest,
    handleAddQuickField,
    removeQuickDynamicField,
    addSingleGuest,
    handleGuestFileSelected,
    clearImportedGuests,
    downloadQuickExcelTemplate,
    handleGenerate,
  }
}
