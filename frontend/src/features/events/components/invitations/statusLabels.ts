import type { OperationStatus } from '../../api/generationOperationsApi'

export const STATUS_LABEL: Record<OperationStatus, string> = {
  queued: 'في الانتظار',
  running: 'قيد التنفيذ',
  completed: 'مكتملة',
  partial: 'مكتملة جزئيًا',
  failed: 'فشلت',
  cancel_requested: 'جارٍ الإيقاف',
  cancelled: 'متوقفة',
}
