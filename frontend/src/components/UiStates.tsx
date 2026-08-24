import { AlertTriangle, Inbox, Loader2, RefreshCw } from 'lucide-react'

export function LoadingState({ label = 'جار التحميل…' }: { label?: string }) {
  return <div className="ui-state ui-state--loading" role="status" aria-live="polite"><Loader2 className="ui-state__icon ui-spin" size={24} /><span>{label}</span></div>
}

export function ErrorState({ label = 'تعذر تحميل البيانات', onRetry }: { label?: string; onRetry?: () => void }) {
  return <div className="ui-state ui-state--error" role="alert"><AlertTriangle className="ui-state__icon" size={24} /><span>{label}</span>{onRetry && <button type="button" className="ui-state__action" onClick={onRetry}><RefreshCw size={15} /> إعادة المحاولة</button>}</div>
}

export function EmptyState({ label = 'لا توجد بيانات' }: { label?: string }) {
  return <div className="ui-state ui-state--empty" role="status"><Inbox className="ui-state__icon" size={24} /><span>{label}</span></div>
}
