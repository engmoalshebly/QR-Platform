/**
 * invitations/types.ts
 * Shared types, constants, and helper functions for the invitation generation system.
 * Extracted from the monolithic EventInvitationsTab.tsx.
 */
import { EventModel, EventStats } from '../../types'

// ═══════════════════════════════════════════════════════════════
// Props & Core Types
// ═══════════════════════════════════════════════════════════════

export interface InvitationsTabProps {
  event: EventModel
  stats?: EventStats
}

export type GenerationSource = 'quick' | 'design'
export type QuickInputMode = 'manual' | 'names' | 'excel'
export type DesignInputMode = 'count' | 'names' | 'excel'

export type GuestImportRow = {
  guest_name: string
  invitation_count: number
  ticket_class: 'vip' | 'normal'
  custom_fields?: Record<string, string>
}

export interface DesignExcelColumn {
  name: string
  index: number
  sampleValues: string[]
}

export interface DynamicField {
  data_key: string
  label: string
  element_type: string
  required: boolean
}

// ═══════════════════════════════════════════════════════════════
// Constants
// ═══════════════════════════════════════════════════════════════

export const GRID_PRESETS = [
  { label: '3×3', rows: 3, cols: 3 },
  { label: '4×4', rows: 4, cols: 4 },
  { label: '5×5', rows: 5, cols: 5 },
  { label: '4×6', rows: 6, cols: 4 },
  { label: '5×8', rows: 8, cols: 5 },
] as const

export const BARCODE_SIZES = [
  { label: 'تلقائي', value: null },
  { label: '200px', value: 200 },
  { label: '300px', value: 300 },
  { label: '400px', value: 400 },
  { label: '500px', value: 500 },
  { label: '600px', value: 600 },
] as const

export const BUILTIN_FIELDS: DynamicField[] = [
  { data_key: 'guest.name', label: 'اسم الضيف', element_type: 'guest_name', required: true },
]

export const ALIAS_MAP: Record<string, string[]> = {
  'guest.name': ['اسم الضيف', 'guest_name', 'name', 'اسم', 'الاسم', 'guestname', 'الضيف'],
  'event.date': ['تاريخ', 'event_date', 'date', 'التاريخ'],
  'event.time': ['وقت', 'event_time', 'time', 'الوقت'],
  'custom.seat': ['مقعد', 'seat_number', 'seat', 'رقم المقعد'],
  'custom.table': ['طاولة', 'table_number', 'table', 'رقم الطاولة'],
  'custom.gate': ['بوابة', 'gate', 'البوابة'],
  'custom.hall': ['قاعة', 'hall', 'القاعة'],
}

// Reserved field names that cannot be used as custom field names
export const RESERVED_FIELD_NAMES = [
  'اسم الضيف', 'guest_name', 'name',
  'عدد الأشخاص', 'عدد الدعوات', 'invitation_count', 'count',
  'نوع التذكرة', 'ticket_class', 'class', 'الفئة',
  'عدد المرافقين',
]

// Column names treated as core (not custom) during Excel parsing
export const CORE_EXCEL_COLUMNS = [
  'اسم الضيف', 'guest_name', 'name',
  'عدد الأشخاص', 'عدد الدعوات', 'invitation_count', 'count',
  'نوع التذكرة', 'ticket_class', 'class',
]

// ═══════════════════════════════════════════════════════════════
// Helper Functions
// ═══════════════════════════════════════════════════════════════

/** Convert Arabic/Eastern Arabic digits to Western digits */
export const sanitizeArabicDigits = (val: any): string => {
  return String(val || '').replace(/[٠-٩]/g, (c) => String(c.charCodeAt(0) - 0x0660))
}

/** Check if a field name refers to a phone number */
export const isPhoneField = (name: string): boolean => {
  const n = String(name || '').trim().toLowerCase().replace(/[\s-_]/g, '')
  return [
    'جوال', 'رقمجوال', 'هاتف', 'رقمهاتف', 'موبايل', 'الموبايل',
    'الهاتفالمحمول', 'تليفون', 'الهاتف', 'phone', 'mobile', 'tel',
    'whatsapp', 'واتساب',
  ].some(alias => n.includes(alias))
}

/** Check if a field name refers to an email address */
export const isEmailField = (name: string): boolean => {
  const n = String(name || '').trim().toLowerCase().replace(/[\s-_]/g, '')
  return [
    'بريد', 'بريدإلكتروني', 'البريدالإلكتروني', 'بريدالكتروني',
    'الالكتروني', 'البريدالالكتروني', 'الايميل', 'ايميل', 'email',
  ].some(alias => n.includes(alias))
}

/** Parse a raw ticket class value into 'vip' or 'normal' */
export const parseTicketClass = (value: unknown): 'vip' | 'normal' => {
  const normalized = String(value ?? '').trim().toLowerCase()
  if (['vip', 'v', 'كبار الشخصيات'].includes(normalized)) return 'vip'
  if (!normalized || ['normal', 'n', 'عادي', 'عادية', 'عام'].includes(normalized)) return 'normal'
  throw new Error('فئة التذكرة غير صالحة. استخدم عادي أو VIP.')
}
