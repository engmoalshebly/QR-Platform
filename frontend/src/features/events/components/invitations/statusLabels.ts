import type { OperationStatus } from '../../api/generationOperationsApi'

export const STATUS_LABEL: Record<OperationStatus, string> = {
  queued: 'بانتظار التنفيذ',
  running: 'جارٍ إنشاء الدعوات',
  completed: 'اكتمل الإنشاء',
  partial: 'اكتمل الإنشاء جزئياً',
  failed: 'تعذر الإكمال',
  cancel_requested: 'جارٍ الإيقاف',
  cancelled: 'متوقفة',
}
