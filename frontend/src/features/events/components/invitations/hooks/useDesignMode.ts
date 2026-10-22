/**
 * useDesignMode.ts
 * Business logic for Design Mode (custom card generation).
 * Handles: manual guest entry, count-based generation, Excel generation,
 * RSVP validation, template selection, Excel template download, and batch generation.
 */
import type { InvitationStateReturn } from './useInvitationState'
import { useCallback } from 'react'
import { EventModel } from '../../../types'
import {
  isPhoneField,
  isEmailField,
  sanitizeArabicDigits,
  ALIAS_MAP,
} from '../types'
import type { DynamicField, DesignExcelColumn } from '../types'
import { BUILTIN_FIELDS } from '../types'
import {
  getCleanFieldLabel,
  resolveGuestName,
  resolveGuestCount,
  resolveTicketClass,
  formatCellValue,
} from '../../../utils/mappingUtils'
import { useQueryClient } from '@tanstack/react-query'
import { useAuthStore } from '@features/auth/store/authStore'
import { batchesApi } from '../../../api/batchesApi'
import { generationOperationsApi, submitOperation } from '../../../api/generationOperationsApi'
import { templatesApi } from '../../../api/templatesApi'
import { downloadSpreadsheet, readSpreadsheet } from '../../../utils/spreadsheet'

export function useDesignMode(state: InvitationStateReturn, event: EventModel) {
  const queryClient = useQueryClient()
  const tenantId = useAuthStore((s) => s.currentTenantId)
  const {
    designManualGuests, setDesignManualGuests,
    designFormName, setDesignFormName,
    designFormCount, setDesignFormCount,
    designFormPhone, setDesignFormPhone,
    designFormEmail, setDesignFormEmail,
    designFormCustomFields, setDesignFormCustomFields,
    designTemplateId,
    designTemplateName,
    designTicketClass,
    designInputMode,
    designCount,
    guestPrefix,
    requireRsvp,
    setLocalError,
    dynamicFields, setDynamicFields,
    setDesignTemplateElements,
    designExcelFile, setDesignExcelFile,
    setDesignExcelColumns,
    designExcelRows, setDesignExcelRows,
    designColumnMapping, setDesignColumnMapping,
    setDesignMappingErrors,
    setDesignExcelReady,
    setIsGeneratingDesigned,
    setDesignStatus,
    setDesignBatchId,
    designedLayout,
    setDesignOperationId,
  } = state

  /** Durable 202 contract when enabled, otherwise the legacy designed batch. */
  const submitDesigned = async (
    invitations: Array<{ guest_name: string; guest_count: number; metadata: { imported_from: string; custom_fields: Record<string, string>; [key: string]: any } }>,
    source: 'count' | 'names' | 'excel',
    templateName?: string,
  ) => {
    const caps = await queryClient.fetchQuery({
      queryKey: ['generation-capabilities', tenantId],
      queryFn: generationOperationsApi.capabilities,
      staleTime: 5 * 60_000,
    }).catch(() => null)
    const formats: Array<'pdf' | 'zip'> = state.canExport === false ? [] : ['pdf', 'zip']
    if (caps?.enabled) {
      const operation = await submitOperation({
        contract_version: 1,
        event_id: event.id,
        mode: 'designed',
        source: source === 'count' ? 'names' : source,
        rows: invitations.map((row) => ({ ...row, ticket_class: designTicketClass })),
        templates: { [designTicketClass]: designTemplateId },
        layout: designedLayout as unknown as Record<string, unknown>,
        output_formats: formats,
        require_rsvp: requireRsvp,
        original_filename: source === 'excel' ? designExcelFile?.name : undefined,
      }, String(tenantId))
      setDesignOperationId(operation.id)
      setDesignStatus(null)
      queryClient.invalidateQueries({ queryKey: ['generation-operations', tenantId, event.id] })
      return
    }
    try {
    const batch = await batchesApi.generateDesignedFast({
      event_id: event.id,
      template_id: designTemplateId,
      ticket_class: designTicketClass,
      invitations,
      layout: designedLayout,
      output_formats: formats,
      barcode_format: 'qr',
      metadata: { template_name: templateName || undefined, source },
    })
    setDesignBatchId(batch.id)
    setDesignStatus(`تم إنشاء الدعوات المصمم (${invitations.length} دعوة)`)
    } catch (error) {
      if ((error as { response?: { data?: { detail?: { code?: string } } } })?.response?.data?.detail?.code !== 'GENERATION_CONTRACT_UPGRADE') throw error
      await queryClient.invalidateQueries({ queryKey: ['generation-capabilities', tenantId] })
      const operation = await submitOperation({
        contract_version: 1, event_id: event.id, mode: 'designed',
        source: source === 'count' ? 'names' : source,
        rows: invitations.map(row => ({ ...row, ticket_class: designTicketClass })),
        templates: { [designTicketClass]: designTemplateId },
        layout: designedLayout as unknown as Record<string, unknown>,
        output_formats: formats, require_rsvp: requireRsvp,
        original_filename: source === 'excel' ? designExcelFile?.name : undefined,
      }, String(tenantId))
      setDesignOperationId(operation.id)
      setDesignStatus(null)
      queryClient.invalidateQueries({ queryKey: ['generation-operations', tenantId, event.id] })
    }
  }

  // ═══════════════════════════════════════════════════════════
  // Design Manual Guests
  // ═══════════════════════════════════════════════════════════

  const addDesignManualGuest = () => {
    const name = designFormName.trim()
    if (!name) {
      setLocalError('يرجى كتابة اسم الضيف')
      return
    }
    if (name.length > 200 || !Number.isInteger(designFormCount) || designFormCount < 1 || designFormCount > 100) {
      setLocalError('اسم الضيف بحد أقصى 200 حرف، وعدد الأشخاص عدد صحيح من 1 إلى 100.')
      return
    }
    if (requireRsvp) {
      const phone = designFormPhone.trim()
      const email = designFormEmail.trim()
      if (!phone && !email) {
        setLocalError('يجب إدخال رقم الجوال أو البريد الإلكتروني للضيف لتفعيل تأكيد الحضور.')
        return
      }
    }

    // Copy the custom fields form state
    const customFields: Record<string, string> = {}
    for (const field of dynamicFields) {
      if (field.data_key !== 'guest.name') {
        customFields[field.data_key] = designFormCustomFields[field.data_key] || ''
      }
    }

    const phoneField = dynamicFields.find(f => isPhoneField(f.data_key) || isPhoneField(f.label))
    const phoneKey = phoneField ? phoneField.data_key : 'رقم الجوال'
    if (requireRsvp || designFormPhone.trim()) {
      customFields[phoneKey] = designFormPhone.trim()
    }

    const emailField = dynamicFields.find(f => isEmailField(f.data_key) || isEmailField(f.label))
    const emailKey = emailField ? emailField.data_key : 'البريد الإلكتروني'
    if (requireRsvp || designFormEmail.trim()) {
      customFields[emailKey] = designFormEmail.trim()
    }

    setDesignManualGuests((prev) => [
      ...prev,
      {
        guest_name: name,
        invitation_count: designFormCount,
        ticket_class: designTicketClass,
        custom_fields: customFields,
      },
    ])
    setDesignFormName('')
    setDesignFormPhone('')
    setDesignFormEmail('')
    setDesignFormCount(1)
    setDesignFormCustomFields({})
    setLocalError(null)
  }

  const deleteDesignManualGuest = (index: number) => {
    setDesignManualGuests((prev) => prev.filter((_, i) => i !== index))
  }

  // ═══════════════════════════════════════════════════════════
  // Excel Mapping Helpers
  // ═══════════════════════════════════════════════════════════

  const findDesignMappingMatch = useCallback((dataKey: string, label: string, columns: DesignExcelColumn[]): string | null => {
    const aliases = ALIAS_MAP[dataKey] || []
    const potentialMatches = [...aliases, label, dataKey]
    for (const col of columns) {
      const colLower = col.name.toLowerCase().trim()
      if (potentialMatches.some((alias) => colLower === alias.toLowerCase())) return col.name
    }
    for (const col of columns) {
      const colLower = col.name.toLowerCase().trim()
      if (potentialMatches.some((alias) => colLower.includes(alias.toLowerCase()) || alias.toLowerCase().includes(colLower))) return col.name
    }
    return null
  }, [])

  const validateDesignMapping = useCallback((mapping: Record<string, string>, rows = designExcelRows) => {
    const errors: string[] = []
    for (const field of dynamicFields) {
      if (field.required && !mapping[field.data_key]) {
        errors.push(`حقل مطلوب: ${field.label}`)
      } else if (field.required && rows.some(row => !String(row[mapping[field.data_key]] ?? '').trim())) {
        errors.push(`توجد خلايا فارغة في الحقل المطلوب: ${field.label}. أكملها في الملف ثم ارفعه مجدداً.`)
      }
    }
    setDesignMappingErrors(errors)
    setDesignExcelReady(errors.length === 0)
  }, [dynamicFields, designExcelRows, setDesignExcelReady, setDesignMappingErrors])

  const handleDesignExcelUpload = async (file: File | null) => {
    if (!file) return
    setLocalError(null)
    try {
      const rows = (await readSpreadsheet(file)).map((row) =>
        Object.fromEntries(
          Object.entries(row).map(([key, value]) => [key, String(value ?? '')]),
        ),
      )
      if (!rows.length) {
        setLocalError('الملف فارغ أو لا يحتوي على بيانات صالحة')
        return
      }
      const columnNames = Object.keys(rows[0])
      const columns: DesignExcelColumn[] = columnNames.map((name, index) => ({
        name, index,
        sampleValues: rows.slice(0, 3).map((row) => String(row[name] || '')),
      }))
      setDesignExcelFile(file)
      setDesignExcelColumns(columns)
      setDesignExcelRows(rows)
      const mapping: Record<string, string> = {}
      for (const field of dynamicFields) {
        const match = findDesignMappingMatch(field.data_key, field.label, columns)
        if (match) mapping[field.data_key] = match
      }
      setDesignColumnMapping(mapping)
      validateDesignMapping(mapping, rows)
    } catch {
      setLocalError('تعذر قراءة الملف. استخدم ملف XLSX أو CSV')
    }
  }

  const handleDesignMappingChange = (dataKey: string, columnName: string) => {
    const newMapping = { ...designColumnMapping, [dataKey]: columnName }
    setDesignColumnMapping(newMapping)
    validateDesignMapping(newMapping)
  }

  const clearDesignExcel = () => {
    setDesignExcelFile(null)
    setDesignExcelColumns([])
    setDesignExcelRows([])
    setDesignColumnMapping({})
    setDesignMappingErrors([])
    setDesignExcelReady(false)
  }

  // ═══════════════════════════════════════════════════════════
  // Generate Designed (from Excel)
  // ═══════════════════════════════════════════════════════════

  const handleGenerateDesignedFromExcel = async () => {
    if (!designTemplateId || !designExcelRows.length) return
    setIsGeneratingDesigned(true)
    setLocalError(null)
    setDesignStatus(null)
    setDesignBatchId('')

    try {
      const invitations: Array<{
        guest_name: string
        guest_count: number
        metadata: { imported_from: string; custom_fields: Record<string, string>; require_rsvp?: boolean }
      }> = []

      const guestNameCol = designColumnMapping['guest.name']

      for (const row of designExcelRows) {
        const rowTicketClass = resolveTicketClass(row, designTicketClass)
        if (rowTicketClass !== designTicketClass) {
          throw new Error('الملف يحتوي فئات مختلفة. استخدم الاستيراد الخادمي بقالب لكل فئة، أو ارفع ملفاً للفئة المحددة فقط؛ لم يتم إنشاء أي دعوة.')
        }

        const guestName = resolveGuestName(row, guestNameCol)
        const invitationCount = resolveGuestCount(row)

        const customFields: Record<string, string> = {}
        for (const field of dynamicFields) {
          if (field.data_key !== 'guest.name') {
            const colName = designColumnMapping[field.data_key]
            if (colName && row[colName]) {
              customFields[field.data_key] = sanitizeArabicDigits(String(formatCellValue(row[colName])))
            }
          }
        }

        // Contacts are delivery data, independent of the fields printed on the card.
        for (const key of Object.keys(row)) {
          if (isPhoneField(key) || isEmailField(key)) customFields[key] = String(formatCellValue(row[key])).trim()
        }
        if (requireRsvp && !Object.keys(customFields).some(key => (isPhoneField(key) || isEmailField(key)) && customFields[key])) {
          throw new Error('يجب إدخال رقم دولي أو بريد إلكتروني لكل ضيف لتفعيل تأكيد الحضور.')
        }

        invitations.push({
          guest_name: guestName,
          guest_count: invitationCount,
          metadata: {
            imported_from: designExcelFile?.name || 'Excel',
            custom_fields: customFields,
            require_rsvp: requireRsvp,
          },
        })
      }

      if (!invitations.length) throw new Error('لم يتم إنشاء أي دعوات صالحة')
      if (invitations.length > 1000) throw new Error('الحد الحالي 1000 دعوة للعملية الواحدة. قسّم الملف إلى دفعات أصغر.')

      setDesignStatus('جاري إرسال الطلب والإنشاء...')
      await submitDesigned(invitations, 'excel', designTemplateName)
    } catch (err: any) {
      setLocalError(err)
    } finally {
      setIsGeneratingDesigned(false)
    }
  }

  // ═══════════════════════════════════════════════════════════
  // Generate Designed (from names/count)
  // ═══════════════════════════════════════════════════════════

  const handleGenerateDesigned = async () => {
    if (!designTemplateId) {
      setLocalError('احفظ القالب أولاً من محرر التصميم')
      return
    }

    setLocalError(null)
    setDesignStatus(null)
    setIsGeneratingDesigned(true)
    setDesignBatchId('')

    if (requireRsvp) {
      if (designInputMode === 'count') {
        setLocalError('لا يمكن تفعيل تأكيد الحضور عند الإنشاء بالعدد لعدم وجود بيانات اتصال للضيوف.')
        setIsGeneratingDesigned(false)
        return
      }

      if (designInputMode === 'names') {
        const invalidGuests = designManualGuests.filter(g => {
          const fields = g.custom_fields || {}
          const hasPhone = Object.keys(fields).some(k => isPhoneField(k) && (fields[k] || '').trim())
          const hasEmail = Object.keys(fields).some(k => isEmailField(k) && (fields[k] || '').trim())
          return !hasPhone && !hasEmail
        })

        if (invalidGuests.length > 0) {
          const names = invalidGuests.map(g => g.guest_name).join('، ')
          setLocalError(`الضيوف التاليين يفتقرون لبيانات الاتصال (الهاتف أو البريد الإلكتروني): ${names}`)
          setIsGeneratingDesigned(false)
          return
        }
      }
    }

    try {
      let invitations: Array<{
        guest_name: string
        guest_count: number
        metadata: { imported_from: string; custom_fields: Record<string, string>; require_rsvp?: boolean }
      }> = []

      if (designInputMode === 'names') {
        if (designManualGuests.length === 0) {
          throw new Error('القائمة فارغة. يرجى إضافة ضيف واحد على الأقل.')
        }
        invitations = designManualGuests.map((guest) => ({
          guest_name: guest.guest_name,
          guest_count: guest.invitation_count,
          metadata: {
            imported_from: 'Manual List',
            custom_fields: guest.custom_fields || {},
            require_rsvp: requireRsvp,
          },
        }))
      } else {
        if (!Number.isInteger(designCount) || designCount < 1 || designCount > 1000) {
          throw new Error('عدد الدعوات يجب أن يكون عددًا صحيحًا من 1 إلى 1000')
        }
        invitations = Array.from({ length: designCount }, (_, i) => ({
          guest_name: `${guestPrefix} ${i + 1}`,
          guest_count: 1,
          metadata: {
            imported_from: 'Quick Mode',
            custom_fields: {},
            require_rsvp: requireRsvp,
          },
        }))
      }

      setDesignStatus('جاري إرسال الطلب والإنشاء...')
      await submitDesigned(invitations, designInputMode === 'names' ? 'names' : 'count', designTemplateName)
    } catch (err: any) {
      setLocalError(err)
    } finally {
      setIsGeneratingDesigned(false)
    }
  }

  // ═══════════════════════════════════════════════════════════
  // Design Excel Template Download
  // ═══════════════════════════════════════════════════════════

  const downloadDesignExcelTemplate = async () => {
    const customKeys = new Set<string>()
    dynamicFields.forEach((field) => {
      const dk = field.data_key || ''
      if (dk && dk.trim()) {
        const key = dk.trim()
        if (!['اسم الضيف', 'guest_name', 'name', 'guest.name', 'عدد الدعوات', 'عدد الأشخاص', 'invitation_count', 'count', 'نوع التذكرة', 'ticket_class', 'class'].includes(key)) {
          customKeys.add(key)
        }
      }
    })

    if (requireRsvp) {
      const customKeysList = Array.from(customKeys)
      const hasPhone = customKeysList.some(k => isPhoneField(k))
      const hasEmail = customKeysList.some(k => isEmailField(k))
      if (!hasPhone) customKeys.add('رقم الجوال')
      if (!hasEmail) customKeys.add('البريد الإلكتروني')
    }

    const baseHeaders = ['اسم الضيف', 'عدد الدعوات', 'نوع التذكرة']
    const allHeaders = [...baseHeaders, ...Array.from(customKeys)]

    const expectedRows = designInputMode === 'names'
      ? designManualGuests.length
      : designInputMode === 'excel'
      ? designExcelRows.length
      : designCount

    const rowsCount = expectedRows > 0 ? expectedRows : 5
    const dummyRows: Record<string, any>[] = []

    if (designInputMode === 'names' && designManualGuests.length > 0) {
      designManualGuests.forEach((guest) => {
        const row: Record<string, any> = {
          'اسم الضيف': guest.guest_name,
          'عدد الدعوات': guest.invitation_count,
          'نوع التذكرة': guest.ticket_class === 'vip' ? 'VIP' : 'normal'
        }
        customKeys.forEach((key) => {
          const existingVal = guest.custom_fields?.[key]
          if (existingVal !== undefined && existingVal !== null && String(existingVal).trim() !== '') {
            row[key] = existingVal
          } else {
            row[key] = ''
          }
        })
        dummyRows.push(row)
      })
    } else if (designInputMode === 'excel' && designExcelRows.length > 0) {
      designExcelRows.forEach((exRow) => {
        const row: Record<string, any> = {}
        allHeaders.forEach(header => {
          row[header] = exRow[header] || ''
        })
        dummyRows.push(row)
      })
    } else {
      for (let i = 0; i < rowsCount; i++) {
        const row: Record<string, any> = {
          'اسم الضيف': `ضيف ${i + 1}`,
          'عدد الدعوات': 1,
          'نوع التذكرة': designTicketClass === 'vip' ? 'VIP' : 'normal'
        }
        customKeys.forEach((key) => {
          if (isPhoneField(key) || isEmailField(key)) {
            row[key] = ''
          } else {
            row[key] = `بيانات ${key}`
          }
        })
        dummyRows.push(row)
      }
    }

    const guideRows = [
      { 'العمود': 'اسم الضيف', 'النوع': 'نص (إلزامي)', 'الوصف': 'الاسم الكامل للضيف المطبوع على البطاقة' },
      { 'العمود': 'عدد الدعوات', 'النوع': 'رقم (اختياري)', 'الوصف': 'عدد البطاقات المطلوب إنشاؤها لهذا الضيف (الافتراضي 1)' },
      { 'العمود': 'نوع التذكرة', 'النوع': 'VIP أو normal (اختياري)', 'الوصف': 'فئة التذكرة الخاصة بالضيف (VIP أو عادي)' },
    ]
    customKeys.forEach((key) => {
      if (isPhoneField(key)) {
        guideRows.push({ 'العمود': key, 'النوع': 'رقم/نص (مطلوب لتأكيد الحضور)', 'الوصف': 'رقم الهاتف لإرسال رابط تأكيد الحضور' })
      } else if (isEmailField(key)) {
        guideRows.push({ 'العمود': key, 'النوع': 'نص (مطلوب لتأكيد الحضور)', 'الوصف': 'البريد الإلكتروني لإرسال رابط تأكيد الحضور' })
      } else {
        guideRows.push({
          'العمود': key,
          'النوع': 'نص (حسب التصميم)',
          'الوصف': `الحقل المخصص المربوط بـ "${key}" في التصميم الخاص بك`
        })
      }
    })
    await downloadSpreadsheet([
      { name: 'المدعوين', rows: dummyRows, headers: allHeaders },
      { name: 'دليل تعبئة الحقول', rows: guideRows },
    ], `نموذج_دعوات_تصميم_${designTemplateName.replace(/\s+/g, '_') || 'مخصص'}.xlsx`)
  }

  // ═══════════════════════════════════════════════════════════
  // Dynamic Fields (fetched when template changes)
  // ═══════════════════════════════════════════════════════════

  const fetchDynamicFields = useCallback(async (templateId: string) => {
    if (!templateId) {
      setDynamicFields(BUILTIN_FIELDS)
      setDesignTemplateElements([])
      return
    }
    try {
      const elements = await templatesApi.getElements(templateId)
      setDesignTemplateElements(elements)
      const fields: DynamicField[] = []
      const seenKeys = new Set<string>()
      for (const el of elements) {
        if (el.element_type === 'guest_name') {
          const key = el.data_key || 'guest.name'
          if (!seenKeys.has(key)) {
            seenKeys.add(key)
            fields.push({ data_key: key, label: getCleanFieldLabel(key, el.element_type, el.label), element_type: el.element_type, required: true })
          }
        } else if (el.element_type === 'dynamic_text' && el.data_key) {
          if (!seenKeys.has(el.data_key)) {
            seenKeys.add(el.data_key)
            fields.push({ data_key: el.data_key, label: getCleanFieldLabel(el.data_key, el.element_type, el.label), element_type: el.element_type, required: false })
          }
        } else if (['event_date', 'event_time', 'event_location', 'seat_number', 'gate', 'hall', 'table_number'].includes(el.element_type)) {
          const key = el.data_key || `custom.${el.element_type}`
          if (!seenKeys.has(key)) {
            seenKeys.add(key)
            fields.push({ data_key: key, label: getCleanFieldLabel(key, el.element_type, el.label), element_type: el.element_type, required: false })
          }
        }
      }
      setDynamicFields(fields)
    } catch {
      setDynamicFields(BUILTIN_FIELDS)
      setDesignTemplateElements([])
    }
  }, [setDesignTemplateElements, setDynamicFields])

  return {
    // Manual guests
    addDesignManualGuest,
    deleteDesignManualGuest,
    // Excel mapping
    findDesignMappingMatch,
    validateDesignMapping,
    handleDesignExcelUpload,
    handleDesignMappingChange,
    clearDesignExcel,
    // Generation
    handleGenerateDesignedFromExcel,
    handleGenerateDesigned,
    // Template download
    downloadDesignExcelTemplate,
    // Dynamic fields
    fetchDynamicFields,
  }
}
