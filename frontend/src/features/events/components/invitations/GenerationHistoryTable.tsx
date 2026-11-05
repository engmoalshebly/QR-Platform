import { Fragment, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download, FileText, Images, Loader2, RefreshCw, Trash2 } from 'lucide-react'
import { Can, PERM } from '@shared/permissions'
import { useAuthStore } from '@features/auth/store/authStore'
import { invitationsApi } from '../../api/invitationsApi'
import { generationOperationsApi, TERMINAL_STATUSES, type OperationStatus } from '../../api/generationOperationsApi'
import { GenerationResultModal } from './GenerationResultModal'
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
  files?: number
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
  const [openOperation, setOpenOperation] = useState<string | null>(null)
  // Finished operations with files are represented by their batches below;
  // operations without files (plan without PDF export) are listed here too.
  const pending = useQuery({
    queryKey: ['generation-operations', tenantId, eventId, 'history'],
    queryFn: () => generationOperationsApi.list(eventId, undefined, 50),
    enabled: !!tenantId && operationsEnabled,
    refetchInterval: (q) => (q.state.data?.items.some((o) => !TERMINAL_STATUSES.includes(o.status)) && !document.hidden ? 10_000 : false),
    retry: false,
  })

  // An operation can create several batches (one per class). Those batches
  // already list it, so the operation row is hidden and the batches carry its files.
  const batchesOf = (o: { cards_count: number; completed_at: string | null; updated_at: string }) => {
    const end = new Date(o.completed_at ?? o.updated_at).getTime()
    const near = history.filter(h => h.generated_at && Math.abs(new Date(h.generated_at).getTime() - end) < 120_000)
    return near.reduce((sum, h) => sum + h.total_invitations, 0) === o.cards_count ? near : []
  }
  const operations = pending.data?.items ?? []
  const operationOfBatch = (id: string) => operations.find(o => batchesOf(o).some(h => h.id === id))

  const rows: Row[] = [
    ...(pending.data?.items ?? []).filter(o => PENDING.includes(o.status) || batchesOf(o).length === 0).map((o): Row => ({
      key: `op-${o.id}`, title: o.mode === 'designed' ? 'إنشاء من تصميم القالب' : 'إنشاء دعوات برمز دخول', at: o.created_at, vip: o.vip_cards, normal: o.normal_cards,
      total: o.cards_count, status: o.status, operationId: o.id, files: o.files_done,
    })),
    ...history.map((item): Row => {
      const special = item.id === 'registration_submissions' ? 'التسجيل الذاتي' : item.id === 'rsvp_submissions' ? 'ردود الضيوف' : null
      return {
        key: `batch-${item.id}`, title: special ?? (UUID.test(item.id) ? 'إنشاء من تصميم القالب' : 'إنشاء سريع'),
        at: item.generated_at, vip: item.vip_count, normal: item.normal_count, total: item.total_invitations,
        status: 'completed', pdf: item.pdf_url, zip: item.zip_url, historyId: item.id,
        operationId: operationOfBatch(item.id)?.id, files: operationOfBatch(item.id)?.files_done,
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
                          {row.operationId && (row.files ?? 0) > 0 && <button type="button" className="inv-dl-btn inv-dl-btn--zip" onClick={() => setOpenOperation(row.operationId!)}><Download size={14} /> {row.files} ملفات</button>}
                          {!row.pdf && !row.zip && !(row.operationId && (row.files ?? 0) > 0) && <span className="gop-table__muted">—</span>}
                        </div>
                      </Can>
                    </td>
                    <td>
                      <div className="gop-table__actions">
                        <button type="button" className="gop-log__toggle"
                          onClick={() => row.historyId ? onDetails(row.historyId) : setOpenOperation(row.operationId!)}>
                          التفاصيل
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
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {openOperation && <GenerationResultModal operationId={openOperation} onClose={() => setOpenOperation(null)} />}
    </section>
  )
}
