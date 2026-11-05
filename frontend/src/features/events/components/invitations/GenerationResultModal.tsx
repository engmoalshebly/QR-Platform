import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useInfiniteQuery } from '@tanstack/react-query'
import { AlertCircle, ArrowLeft, CheckCircle2, Download, FileText, Images, Loader2, Users, X, XCircle } from 'lucide-react'
import { DownloadFileButton } from '@components/DownloadFileButton'
import { Can, PERM } from '@shared/permissions'
import { useAuthStore } from '@features/auth/store/authStore'
import { generationOperationsApi, TERMINAL_STATUSES, type GenerationArtifact, type GenerationOperation } from '../../api/generationOperationsApi'
import { useGenerationOperation } from '../../hooks/useGenerationOperations'
import { OperationActions, openEventSection } from './GenerationOperationTracker'
import './generation-operations.css'

const pct = (done: number, total: number) => (total > 0 ? Math.min(100, Math.floor((done / total) * 100)) : 0)
const megabytes = (bytes: number) => `${(bytes / 1048576).toFixed(bytes < 104857 ? 2 : 1)} MB`

function Progress({ label, done, total, failed = 0 }: { label: string; done: number; total: number; failed?: number }) {
  return (
    <div className="gom-progress">
      <div className="gom-progress__head"><span>{label}</span><b>{done} / {total}{failed > 0 && <em> · فشل {failed}</em>}</b></div>
      <div className="gom-progress__bar" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct(done, total)}>
        <i style={{ width: `${pct(done, total)}%` }} />
      </div>
    </div>
  )
}

function FileCards({ operationId }: { operationId: string }) {
  const tenantId = useAuthStore(s => s.currentTenantId)
  const query = useInfiniteQuery({
    queryKey: ['generation-artifacts', tenantId, operationId],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) => generationOperationsApi.artifacts(operationId, pageParam),
    getNextPageParam: page => page.next_cursor ?? undefined,
  })
  if (query.isLoading) return <p className="gom-muted"><Loader2 size={14} className="animate-spin" /> جارٍ تجهيز الملفات…</p>
  if (query.isError) return <p className="gom-muted">لا تتوفر الملفات لهذا الحساب (يلزم صلاحية التصدير).</p>
  const files = query.data?.pages.flatMap(page => page.items) ?? []
  if (!files.length) return null
  const groups: Array<[GenerationArtifact['kind'], string, string]> = [
    ['pdf', 'ملف الطباعة PDF', 'صفحات جاهزة للطباعة مباشرة'],
    ['zip', 'صور الدعوات ZIP', 'صورة منفصلة لكل دعوة، للإرسال الرقمي'],
  ]
  return (
    <div className="gom-files">
      {groups.map(([kind, title, hint]) => {
        const items = files.filter(file => file.kind === kind)
        if (!items.length) return null
        return (
          <section key={kind} className="gom-files__group">
            <header>
              <span className={`gom-files__icon gom-files__icon--${kind}`}>{kind === 'pdf' ? <FileText size={20} /> : <Images size={20} />}</span>
              <div><strong>{title}</strong><small>{hint}</small></div>
            </header>
            <ul>
              {items.map(file => (
                <li key={file.id}>
                  <div className="gom-file">
                    <div>
                      <strong>{items.length > 1 ? `الجزء ${file.part_index + 1}` : 'الملف كاملاً'}</strong>
                      <small>{file.cards_count} بطاقة · {megabytes(file.byte_size)}</small>
                    </div>
                    <DownloadFileButton
                      url={generationOperationsApi.artifactDownloadPath(operationId, file.id)}
                      filename={`invitations-${file.kind}-${file.part_index + 1}.${file.kind}`}
                      className={`gom-download gom-download--${kind}`}
                    >
                      <Download size={15} /> تنزيل
                    </DownloadFileButton>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )
      })}
      {query.hasNextPage && <button type="button" className="gom-more" disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>عرض المزيد من الملفات</button>}
    </div>
  )
}

function Body({ operation }: { operation: GenerationOperation }) {
  const done = TERMINAL_STATUSES.includes(operation.status)
  const ok = operation.status === 'completed'
  const withFiles = operation.files_expected > 0
  return (
    <>
      <div className="gom-hero">
        <span className={`gom-hero__icon gom-hero__icon--${ok ? 'ok' : done ? 'warn' : 'busy'}`}>
          {ok ? <CheckCircle2 size={34} /> : done ? (operation.status === 'cancelled' ? <XCircle size={34} /> : <AlertCircle size={34} />) : <Loader2 size={34} className="animate-spin" />}
        </span>
        <h2 id="gom-title">
          {ok ? 'تم إنشاء دعواتك' : operation.status === 'partial' ? 'اكتمل الإنشاء جزئياً' : operation.status === 'failed' ? 'تعذر إكمال الإنشاء' : operation.status === 'cancelled' ? 'أُوقف الإنشاء' : 'جارٍ إنشاء دعواتك…'}
        </h2>
        <p>
          {ok ? (withFiles ? 'ملفات الطباعة جاهزة للتنزيل أدناه.' : 'أُنشئت الدعوات برموز الدخول.')
            : done ? (operation.error_message || 'يمكنك إعادة المحاولة؛ الدعوات المنشأة محفوظة ولن تُخصم حصة جديدة.')
            : 'يمكنك إغلاق هذه النافذة، فالعملية تستمر في الخلفية وتجدها في «سجل عمليات الإنشاء».'}
        </p>
      </div>

      {!done && (
        <div className="gom-bars">
          <Progress label="الدعوات" done={operation.cards_done} total={operation.cards_count} failed={operation.cards_failed} />
          {withFiles && <Progress label="ملفات الطباعة" done={operation.files_done} total={Math.max(operation.files_expected, operation.files_done + operation.files_failed)} failed={operation.files_failed} />}
        </div>
      )}

      <div className="gom-stats">
        <div><Users size={16} /><strong>{operation.cards_count}</strong><span>دعوة</span></div>
        <div><strong>{operation.people_count}</strong><span>شخص</span></div>
        <div><strong>{operation.normal_cards}</strong><span>عادي</span></div>
        <div><strong>{operation.vip_cards}</strong><span>VIP</span></div>
      </div>

      {done && operation.status !== 'failed' && withFiles && <Can permission={PERM.INV_EXPORT}><FileCards operationId={operation.id} /></Can>}
      {ok && !withFiles && (
        <p className="gom-note">لا توجد ملفات PDF أو ZIP لهذه العملية. ملفات الطباعة تُنشأ مع الدعوات عند إنشائها وبشرط أن يكون التصدير مفعّلاً لمؤسستك.</p>
      )}
      <OperationActions operation={operation} />
    </>
  )
}

/** Progress and result of one generation, as a dialog. Safe to open for any operation. */
export function GenerationResultModal({ operationId, onClose }: { operationId: string; onClose: () => void }) {
  const { data: operation, isError } = useGenerationOperation(operationId)
  const closeButton = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    closeButton.current?.focus()
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => { document.removeEventListener('keydown', onKey); document.body.style.overflow = ''; previous?.focus?.() }
  }, [onClose])
  const goTo = (tab: 'final_invitations' | 'barcodes') => { onClose(); openEventSection(tab) }
  const done = !!operation && TERMINAL_STATUSES.includes(operation.status)
  return createPortal(
    <div className="gom-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="gom" role="dialog" aria-modal="true" aria-labelledby="gom-title">
        <button ref={closeButton} type="button" className="gom__close" onClick={onClose} aria-label="إغلاق"><X size={18} /></button>
        <div className="gom__body">
          {isError && !operation ? (
            <p role="alert" className="gop__error">تعذر قراءة حالة العملية. ستجدها في «سجل عمليات الإنشاء».</p>
          ) : !operation ? (
            <p className="gom-muted"><Loader2 size={14} className="animate-spin" /> جارٍ قراءة الحالة…</p>
          ) : <Body operation={operation} />}
        </div>
        <footer className="gom__footer">
          <button type="button" className="gom-secondary" onClick={() => goTo('barcodes')}>سجل عمليات الإنشاء</button>
          {done && operation?.status === 'completed' && operation.cards_done > 0 && (
            <button type="button" className="gom-primary" onClick={() => goTo('final_invitations')}>الدعوات الجاهزة للدخول <ArrowLeft size={16} /></button>
          )}
          {!done && <button type="button" className="gom-primary" onClick={onClose}>متابعة في الخلفية</button>}
        </footer>
      </div>
    </div>,
    document.body,
  )
}

/**
 * Where a creation form puts the result: opens the dialog for a new operation
 * and leaves a compact card behind to reopen it.
 */
export function OperationLauncher({ operationId }: { operationId: string }) {
  const { data: operation } = useGenerationOperation(operationId)
  const [open, setOpen] = useState(false)
  const seen = useRef<string | null>(null)
  // Open on a fresh operation only: reloading the page restores old ones silently.
  useEffect(() => {
    if (!operation || seen.current === operation.id) return
    seen.current = operation.id
    if (Date.now() - new Date(operation.created_at).getTime() < 180_000) setOpen(true)
  }, [operation])
  const done = !!operation && TERMINAL_STATUSES.includes(operation.status)
  return (
    <>
      <button type="button" className={`gom-chip${done ? '' : ' is-busy'}`} onClick={() => setOpen(true)}>
        {!operation ? <Loader2 size={16} className="animate-spin" /> : done ? (operation.status === 'completed' ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />) : <Loader2 size={16} className="animate-spin" />}
        <span>{!operation ? 'جارٍ قراءة الحالة…' : done ? 'آخر عملية إنشاء' : 'جارٍ إنشاء الدعوات…'}</span>
        <b>{done ? 'عرض النتيجة والملفات' : 'عرض التقدم'}</b>
      </button>
      {open && <GenerationResultModal operationId={operationId} onClose={() => setOpen(false)} />}
    </>
  )
}
