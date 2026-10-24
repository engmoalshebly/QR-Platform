import { Fragment, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FileText, Images, Loader2, RefreshCw, Trash2 } from 'lucide-react'
import { Can, PERM } from '@shared/permissions'
import { useAuthStore } from '@features/auth/store/authStore'
import { invitationsApi } from '../../api/invitationsApi'
import { generationOperationsApi, TERMINAL_STATUSES, type OperationStatus } from '../../api/generationOperationsApi'
import { GenerationOperationTracker } from './GenerationOperationTracker'
import { STATUS_LABEL } from './statusLabels'
import './generation-operations.css'

type HistoryItem = Awaited<ReturnType<typeof invitationsApi.getGenerationHistory>>[number]
type Filter = 'all' | 'active' | 'attention' | 'completed'
const FILTERS: Array<[Filter, string]> = [['all', 'الكل'], ['active', 'قيد العمل'], ['attention', 'تحتاج متابعة'], ['completed', 'مكتملة']]
const PENDING: OperationStatus[] = ['queued', 'running', 'cancel_requested', 'partial', 'failed']
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

interface Row {
  key: string
  title: string
  at: string | null
  vip: number | null
  normal: number | null
  total: number
  status: OperationStatus
  pdf?: string | null
  zip?: string | null
  historyId?: string
  operationId?: string
}

const rowFilter = (status: OperationStatus): Filter =>
  ['queued', 'running', 'cancel_requested'].includes(status) ? 'active' : ['partial', 'failed'].includes(status) ? 'attention' : 'completed'

/** One table for finished files (batches) and for operations that are still running or need attention. */
export function GenerationHistoryTable({ eventId, operationsEnabled, history, loading, fetching, onRefresh, onDetails, onDelete, deletingId, onDownload, formatDate }: {
  eventId: string
  operationsEnabled: boolean
  history: HistoryItem[]
  loading: boolean
  fetching: boolean
  onRefresh: () => void
  onDetails: (id: string) => void
  onDelete: (item: HistoryItem) => void
  deletingId: string | null
  onDownload: (url: string, fallbackName: string) => void
  formatDate: (value: string | null) => string
}) {
  const tenantId = useAuthStore((s) => s.currentTenantId)
  const [filter, setFilter] = useState<Filter>('all')
  const [open, setOpen] = useState<string | null>(null)
  // Finished operations are already represented by their batches below.
  const pending = useQuery({
    queryKey: ['generation-operations', tenantId, eventId, 'pending'],
    queryFn: () => generationOperationsApi.list(eventId, undefined, 25, PENDING),
    enabled: !!tenantId && operationsEnabled,
    refetchInterval: (q) => (q.state.data?.items.some((o) => !TERMINAL_STATUSES.includes(o.status)) && !document.hidden ? 10_000 : false),
    retry: false,
  })

  const rows: Row[] = [
    ...(pending.data?.items ?? []).map((o): Row => ({
      key: `op-${o.id}`, title: 'عملية إنشاء دعوات', at: o.created_at, vip: o.vip_cards, normal: o.normal_cards,
      total: o.cards_count, status: o.status, operationId: o.id,
    })),
    ...history.map((item): Row => {
      const special = item.id === 'registration_submissions' ? 'التسجيل الذاتي' : item.id === 'rsvp_submissions' ? 'ردود الضيوف' : null
      return {
        key: `batch-${item.id}`, title: special ?? (UUID.test(item.id) ? 'إنشاء من تصميم القالب' : 'إنشاء سريع'),
        at: item.generated_at, vip: item.vip_count, normal: item.normal_count, total: item.total_invitations,
        status: 'completed', pdf: item.pdf_url, zip: item.zip_url, historyId: item.id,
      }
    }),
  ]
  const visible = rows.filter((row) => filter === 'all' || rowFilter(row.status) === filter)
  const busy = loading || pending.isLoading

  return (
    <section className="gop-section" aria-labelledby="gen-ops-title">
      <div className="gop-section__head gop-section__head--row">
        <div><h3 id="gen-ops-title">سجل عمليات الإنشاء</h3><p>كل ما أُنشئ لهذه المناسبة: الملفات الجاهزة، والعمليات الجارية أو التي تحتاج متابعة.</p></div>
        <button type="button" className="gop-log__toggle" onClick={() => { onRefresh(); void pending.refetch() }} disabled={fetching || pending.isFetching} title="تحديث القائمة">
          <RefreshCw size={14} className={fetching || pending.isFetching ? 'animate-spin' : ''} /> تحديث
        </button>
      </div>
      <div className="gop-log__filters" role="group" aria-label="تصفية العمليات">
        {FILTERS.map(([key, label]) => (
          <button key={key} type="button" aria-pressed={filter === key} onClick={() => setFilter(key)}>{label}</button>
        ))}
      </div>
      {busy ? (
        <p className="gop__hint"><Loader2 size={14} className="animate-spin" /> جارٍ تحميل العمليات…</p>
      ) : visible.length === 0 ? (
        <div className="gop-log__empty"><strong>{filter === 'all' ? 'لا توجد عمليات إنشاء بعد' : 'لا توجد عمليات في هذا التصنيف'}</strong><p>{filter === 'all' ? 'ستظهر هنا كل عملية إنشاء مع ملفاتها وحالتها.' : 'جرّب تصنيفاً آخر لعرض بقية العمليات.'}</p></div>
      ) : (
        <div className="gop-table-wrap">
          <table className="gop-table">
            <thead><tr><th>العملية</th><th>التاريخ</th><th>VIP</th><th>عادي</th><th>الإجمالي</th><th>الحالة</th><th>الملفات</th><th aria-label="إجراءات" /></tr></thead>
            <tbody>
              {visible.map((row) => (
                <Fragment key={row.key}>
                  <tr>
                    <td><strong>{row.title}</strong></td>
                    <td className="gop-table__muted">{formatDate(row.at)}</td>
                    <td className="gop-table__num">{row.vip ?? '—'}</td>
                    <td className="gop-table__num">{row.normal ?? '—'}</td>
                    <td className="gop-table__num"><strong>{row.total}</strong></td>
                    <td><span className={`gop-log__status gop-log__status--${row.status}`}>{STATUS_LABEL[row.status]}</span></td>
                    <td>
                      <Can permission={PERM.BATCH_DOWNLOAD}>
                        <div className="gop-table__files">
                          {row.pdf && <button type="button" className="inv-dl-btn inv-dl-btn--pdf" onClick={() => onDownload(row.pdf!, 'invitations.pdf')}><FileText size={14} /> PDF</button>}
                          {row.zip && <button type="button" className="inv-dl-btn inv-dl-btn--zip" onClick={() => onDownload(row.zip!, 'invitations.zip')}><Images size={14} /> ZIP</button>}
                          {!row.pdf && !row.zip && <span className="gop-table__muted">—</span>}
                        </div>
                      </Can>
                    </td>
                    <td>
                      <div className="gop-table__actions">
                        <button type="button" className="gop-log__toggle" aria-expanded={row.operationId ? open === row.key : undefined}
                          onClick={() => row.historyId ? onDetails(row.historyId) : setOpen(open === row.key ? null : row.key)}>
                          {row.operationId && open === row.key ? 'إخفاء' : 'التفاصيل'}
                        </button>
                        {row.historyId && (
                          <Can permission={PERM.BATCH_DELETE}>
                            <button type="button" className="gop-table__delete" title="حذف" aria-label="حذف"
                              disabled={deletingId === row.historyId}
                              onClick={() => { const item = history.find((h) => h.id === row.historyId); if (item) onDelete(item) }}>
                              {deletingId === row.historyId ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                            </button>
                          </Can>
                        )}
                      </div>
                    </td>
                  </tr>
                  {row.operationId && open === row.key && (
                    <tr className="gop-table__detail"><td colSpan={8}><GenerationOperationTracker operationId={row.operationId} /></td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
