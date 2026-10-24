import { useState } from 'react'
import { History } from 'lucide-react'
import { useInfiniteQuery } from '@tanstack/react-query'
import { useAuthStore } from '@features/auth/store/authStore'
import { generationOperationsApi, TERMINAL_STATUSES, type GenerationOperation, type OperationStatus } from '../../api/generationOperationsApi'
import { GenerationOperationTracker } from './GenerationOperationTracker'
import { STATUS_LABEL } from './statusLabels'
import './generation-operations.css'

type Filter = 'all' | 'active' | 'attention' | 'completed'
const FILTERS: Array<[Filter, string]> = [['all', 'الكل'], ['active', 'قيد العمل'], ['attention', 'تحتاج متابعة'], ['completed', 'مكتملة']]
const STATUSES: Record<Filter, OperationStatus[] | undefined> = {
  all: undefined,
  active: ['queued', 'running', 'cancel_requested'],
  attention: ['partial', 'failed'],
  completed: ['completed'],
}

const when = (iso: string) => new Date(iso).toLocaleString('ar', { dateStyle: 'medium', timeStyle: 'short' })

function Row({ operation }: { operation: GenerationOperation }) {
  const [open, setOpen] = useState(!TERMINAL_STATUSES.includes(operation.status))
  return (
    <li className="gop-log__row">
      <div className="gop-log__head">
        <span className="gop-log__title"><strong>{operation.cards_count.toLocaleString('ar-SA')} بطاقة</strong><small>{when(operation.created_at)}</small></span>
        <span className={`gop-log__status gop-log__status--${operation.status}`}>{STATUS_LABEL[operation.status]}</span>
        <button type="button" className="gop-log__toggle" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          {open ? 'إخفاء' : 'التفاصيل'}
        </button>
      </div>
      {/* Detail mounts lazily so a long history never polls hundreds of operations. */}
      {open && <GenerationOperationTracker operationId={operation.id} />}
    </li>
  )
}

/** Paged, filterable history; survives refresh and account/event switches because the server is the source. */
export function GenerationOperationsLog({ eventId }: { eventId: string }) {
  const tenantId = useAuthStore((s) => s.currentTenantId)
  const [filter, setFilter] = useState<Filter>('all')
  const query = useInfiniteQuery({
    queryKey: ['generation-operations', tenantId, eventId, filter],
    queryFn: ({ pageParam }) => generationOperationsApi.list(eventId, pageParam, 25, STATUSES[filter]),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    enabled: !!tenantId,
    refetchInterval: (q) => (q.state.data?.pages[0]?.items.some((o) => !TERMINAL_STATUSES.includes(o.status)) && !document.hidden ? 10_000 : false),
    placeholderData: (previous) => previous,
    retry: false,
  })
  const items = query.data?.pages.flatMap((p) => p.items) ?? []
  if (query.isLoading) return <p className="gop__hint">جارٍ تحميل العمليات…</p>
  if (query.isError) return <p role="alert" className="gop__error">تعذر تحميل عمليات الإنشاء.</p>
  return (
    <section className="gop-log" aria-label="عمليات الإنشاء">
      <div className="gop-log__filters" role="group" aria-label="تصفية العمليات">
        {FILTERS.map(([key, label]) => (
          <button key={key} type="button" aria-pressed={filter === key} onClick={() => setFilter(key)}>{label}</button>
        ))}
      </div>
      {items.length === 0 ? <div className="gop-log__empty"><History size={22} /><strong>{filter === 'all' ? 'لا توجد عمليات إنشاء بعد' : 'لا توجد عمليات في هذا التصنيف'}</strong><p>{filter === 'all' ? 'ستظهر هنا كل عملية إنشاء دعوات مع حالتها وملفاتها بعد أن تبدأ أول عملية.' : 'جرّب تصنيفاً آخر لعرض بقية العمليات.'}</p></div> : <ul className="gop-log__list">{items.map((o) => <Row key={o.id} operation={o} />)}</ul>}
      {query.hasNextPage && (
        <button type="button" className="gop-log__more" disabled={query.isFetchingNextPage} onClick={() => query.fetchNextPage()}>
          {query.isFetchingNextPage ? 'جارٍ التحميل…' : 'عرض المزيد'}
        </button>
      )}
    </section>
  )
}
