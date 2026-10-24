/**
 * The one guest-list template used everywhere guests are added from a file.
 *
 * Every download offers the same sheet, the same columns in the same order and
 * the same instructions, whichever screen it comes from; only the rows (and
 * the design's own fields, appended at the end) change.  The importers accept
 * these exact headers.
 */
import { downloadSpreadsheet } from './spreadsheet'
import { isEmailField, isPhoneField } from '../components/invitations/types'

export const GUEST_TEMPLATE_COLUMNS = [
  { header: 'اسم الضيف', required: 'نعم', hint: 'الاسم كما يُطبع على الدعوة', example: 'أحمد محمد' },
  { header: 'عدد الأشخاص', required: 'لا (الافتراضي 1)', hint: 'عدد من تشملهم الدعوة؛ يصدر لهم رمز دخول واحد (1 إلى 100)', example: 1 },
  { header: 'نوع التذكرة', required: 'لا (الافتراضي عادي)', hint: 'عادي أو VIP', example: 'عادي' },
  { header: 'رقم الجوال', required: 'عند تفعيل تأكيد الحضور (أو البريد)', hint: 'مع رمز الدولة لإرسال الدعوة عبر WhatsApp', example: '+967700000000' },
  { header: 'البريد الإلكتروني', required: 'عند تفعيل تأكيد الحضور (أو الجوال)', hint: 'لإرسال الدعوة بالبريد', example: 'ahmed@example.com' },
  { header: 'رقم المقعد', required: 'لا', hint: 'يظهر على الدعوة إن كان في التصميم', example: '' },
  { header: 'رقم الطاولة', required: 'لا', hint: 'يظهر على الدعوة إن كان في التصميم', example: '' },
  { header: 'ملاحظات', required: 'لا', hint: 'للاستخدام الداخلي، لا تُطبع', example: '' },
] as const

const CORE = new Set<string>(GUEST_TEMPLATE_COLUMNS.map(column => column.header))
/** Older names for the same columns, folded into the fixed headers. */
const RENAMED: Record<string, string> = {
  'عدد الدعوات': 'عدد الأشخاص', invitation_count: 'عدد الأشخاص', count: 'عدد الأشخاص',
  guest_name: 'اسم الضيف', name: 'اسم الضيف', ticket_class: 'نوع التذكرة',
  'رقم الهاتف': 'رقم الجوال', seat_number: 'رقم المقعد', table_number: 'رقم الطاولة',
}
const CLASS_LABEL: Record<string, string> = { vip: 'VIP', normal: 'عادي' }

const fileSafe = (value: string) => value.trim().replace(/[\\/:*?"<>|]+/g, '').replace(/\s+/g, '_').slice(0, 60) || 'المناسبة'

export async function downloadGuestTemplate({ title, rows, customKeys = [] }: {
  /** Event or design name, used in the file name. */
  title: string
  /** Rows to prefill; keys may use older column names. Empty → two example rows. */
  rows?: Array<Record<string, unknown>>
  /** Fields the design prints (data keys), appended after the fixed columns. */
  customKeys?: Iterable<string>
}) {
  const extra = Array.from(new Set(customKeys)).filter(key =>
    key && !CORE.has(key) && !RENAMED[key] && !isPhoneField(key) && !isEmailField(key)
    && !/^(event|invite)\./.test(key))  // filled from the event, not per guest
  const headers = [...GUEST_TEMPLATE_COLUMNS.map(column => column.header), ...extra]

  const source = rows && rows.length ? rows : [
    { 'اسم الضيف': 'أحمد محمد', 'عدد الأشخاص': 1, 'نوع التذكرة': 'عادي' },
    { 'اسم الضيف': 'سارة علي', 'عدد الأشخاص': 2, 'نوع التذكرة': 'VIP' },
  ]
  const normalized = source.map(row => {
    const out: Record<string, unknown> = Object.fromEntries(headers.map(header => [header, '']))
    for (const [key, value] of Object.entries(row)) {
      const target = RENAMED[key] ?? (isPhoneField(key) ? 'رقم الجوال' : isEmailField(key) ? 'البريد الإلكتروني' : key)
      if (target in out) out[target] = value
    }
    const ticket = String(out['نوع التذكرة'] ?? '').trim().toLowerCase()
    out['نوع التذكرة'] = CLASS_LABEL[ticket] ?? (out['نوع التذكرة'] || 'عادي')
    if (out['عدد الأشخاص'] === '' || out['عدد الأشخاص'] == null) out['عدد الأشخاص'] = 1
    return out
  })

  const guide = [
    ...GUEST_TEMPLATE_COLUMNS.map(column => ({ 'العمود': column.header, 'مطلوب': column.required, 'الوصف': column.hint, 'مثال': column.example })),
    ...extra.map(key => ({ 'العمود': key, 'مطلوب': 'حسب التصميم', 'الوصف': `حقل يُطبع في التصميم باسم «${key}»`, 'مثال': '' })),
  ]

  await downloadSpreadsheet([
    { name: 'المدعوون', rows: normalized, headers },
    { name: 'طريقة التعبئة', rows: guide },
  ], `نموذج_الضيوف_${fileSafe(title)}.xlsx`)
}
