import { useState } from 'react'
import { useMutation, useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, CheckCircle2, Download, Loader2, RotateCcw, XCircle } from 'lucide-react'
import { DownloadFileButton } from '@components/DownloadFileButton'
import { getApiErrorMessage } from '@services/http/client'
import { Can, PERM } from '@shared/permissions'
import { useAuthStore } from '@features/auth/store/authStore'
import {
  generationOperationsApi,
  TERMINAL_STATUSES,
  type GenerationOperation,
} from '../../api/generationOperationsApi'
import { useGenerationOperation } from '../../hooks/useGenerationOperations'
import { STATUS_LABEL } from './statusLabels'
import './generation-operations.css'


const pct = (done: number, total: number) => (total > 0 ? Math.min(100, Math.floor((done / total) * 100)) : 0)

function Meter({ label, done, failed, total }: { label: string; done: number; failed: number; total: number }) {
  return (
    <div className="gop-meter">
      <div className="gop-meter__head">
        <span>{label}</span>
        <span>{done} / {total}{failed > 0 && <b className="gop-bad"> · فشل {failed}</b>}</span>
      </div>
      <div className="gop-meter__bar" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct(done, total)}>
        <div style={{ width: `${pct(done, total)}%` }} />
      </div>
    </div>
  )
}

/** Cards and files are shown separately; a 202 is "accepted", never "finished". */
export function OperationSummary({ operation, filesExpected }: { operation: GenerationOperation; filesExpected: number }) {
  const { status } = operation
  return (
    <div className={`gop gop--${status}`} role="status" aria-live="polite">
      <div className="gop__title">
        {status === 'completed' ? <CheckCircle2 size={18} /> :
          status === 'failed' || status === 'partial' ? <AlertCircle size={18} /> :
          status === 'cancelled' ? <XCircle size={18} /> : <Loader2 size={18} className="animate-spin" />}
        <strong>{STATUS_LABEL[status]}</strong>
        <span className="gop__meta">{operation.cards_count} بطاقة · {operation.people_count} شخص</span>
      </div>
      {!TERMINAL_STATUSES.includes(status) && (
        <p className="gop__hint">بدأت العملية، يمكنك مغادرة الصفحة ومتابعتها لاحقًا من «عمليات الإنشاء».</p>
      )}
      <Meter label="البطاقات" done={operation.cards_done} failed={operation.cards_failed} total={operation.cards_count} />
      {filesExpected > 0 && (
        <Meter label="الملفات" done={operation.files_done} failed={operation.files_failed} total={Math.max(filesExpected, operation.files_done + operation.files_failed)} />
      )}
      <p className="gop__hint">
        VIP: {operation.vip_cards} بطاقة ({operation.vip_people} شخص) · عادي: {operation.normal_cards} بطاقة ({operation.normal_people} شخص)
      </p>
      {(status === 'partial' || status === 'failed') && (
        <p role="alert" className="gop__error">
          {operation.error_message || 'تعذر إكمال بعض المخرجات.'} الدعوات المنشأة محفوظة؛ إعادة المحاولة تعيد الجزء الفاشل فقط ولا تخصم حصة جديدة.
        </p>
      )}
      {status === 'cancelled' && (
        <p className="gop__hint">إيقاف الإنشاء لا يلغي الدعوات التي أُنشئت؛ إلغاء الدعوات إجراء منفصل.</p>
      )}
    </div>
  )
}

export function OperationFiles({ operationId }: { operationId: string }) {
  const tenantId = useAuthStore(s => s.currentTenantId)
  const { data, isLoading, isError, hasNextPage, fetchNextPage, isFetchingNextPage } = useInfiniteQuery({
    queryKey: ['generation-artifacts', tenantId, operationId],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) => generationOperationsApi.artifacts(operationId, pageParam),
    getNextPageParam: page => page.next_cursor ?? undefined,
  })
  if (isLoading) return <p className="gop__hint">جارٍ تحميل الملفات…</p>
  if (isError) return <p className="gop__hint">لا تتوفر الملفات لهذا الحساب (يلزم صلاحية التصدير).</p>
  if (!data?.pages.some(page => page.items.length)) return null
  return (
    <ul className="gop-files">
      {data.pages.flatMap(page => page.items).map((a) => (
        <li key={a.id}>
          <DownloadFileButton
            url={generationOperationsApi.artifactDownloadPath(operationId, a.id)}
            filename={`invitations-${a.kind}-${a.part_index + 1}.${a.kind}`}
            className="inv-dl-btn inv-dl-btn--zip"
          >
            <Download size={14} /> {a.kind.toUpperCase()} · جزء {a.part_index + 1} · {a.cards_count} بطاقة · {(a.byte_size / 1048576).toFixed(1)}MB
          </DownloadFileButton>
        </li>
      ))}
      {hasNextPage && <li><button type="button" className="inv-dl-btn" disabled={isFetchingNextPage} onClick={() => void fetchNextPage()}>
        {isFetchingNextPage ? 'جارٍ تحميل الملفات…' : 'عرض المزيد من الملفات'}
      </button></li>}
    </ul>
  )
}

export function OperationActions({ operation }: { operation: GenerationOperation }) {
  const queryClient = useQueryClient()
  const tenantId = useAuthStore((s) => s.currentTenantId)
  const [error, setError] = useState<string | null>(null)
  const refresh = (op: GenerationOperation) => {
    queryClient.setQueryData(['generation-operation', tenantId, op.id], op)
    queryClient.invalidateQueries({ queryKey: ['generation-operation'] })
  }
  const cancel = useMutation({ mutationFn: () => generationOperationsApi.cancel(operation.id), onSuccess: refresh, onError: (e) => setError(getApiErrorMessage(e)) })
  const retry = useMutation({ mutationFn: () => generationOperationsApi.retry(operation.id), onSuccess: refresh, onError: (e) => setError(getApiErrorMessage(e)) })
  const active = ['queued', 'running'].includes(operation.status)
  const retryable = ['partial', 'failed'].includes(operation.status)
  if (!active && !retryable) return null
  return (
    <Can permission={PERM.INV_GENERATE}>
      <div className="gop-actions">
        {active && (
          <button type="button" className="inv-dl-btn" disabled={cancel.isPending} onClick={() => { setError(null); cancel.mutate() }}>
            <XCircle size={14} /> إيقاف الإنشاء
          </button>
        )}
        {retryable && (
          <button type="button" className="inv-dl-btn" disabled={retry.isPending} onClick={() => { setError(null); retry.mutate() }}>
            <RotateCcw size={14} /> إعادة الجزء الفاشل
          </button>
        )}
        {error && <span role="alert" className="gop-bad">{error}</span>}
      </div>
    </Can>
  )
}

/** Full follow-up view for one operation, safe to remount after a refresh. */
export function GenerationOperationTracker({ operationId }: { operationId: string }) {
  const { data: operation, isError } = useGenerationOperation(operationId)
  if (isError && !operation) return <p role="alert" className="gop__error">تعذر قراءة حالة العملية. ستجدها في «عمليات الإنشاء».</p>
  if (!operation) return <p className="gop__hint"><Loader2 size={14} className="animate-spin" /> جارٍ قراءة الحالة…</p>
  const done = TERMINAL_STATUSES.includes(operation.status)
  return (
    <div className="gop-wrap">
      <OperationSummary operation={operation} filesExpected={operation.files_expected} />
      <OperationActions operation={operation} />
      {done && operation.status !== 'failed' && operation.files_expected > 0 && (
        <Can permission={PERM.INV_EXPORT}><OperationFiles operationId={operation.id} /></Can>
      )}
    </div>
  )
}
