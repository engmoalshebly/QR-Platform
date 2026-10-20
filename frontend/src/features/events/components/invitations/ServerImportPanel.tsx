import { useEffect, useRef, useState } from 'react'
import { useInfiniteQuery } from '@tanstack/react-query'
import { AlertCircle, FileSpreadsheet, Loader2, RefreshCw, Upload } from 'lucide-react'
import { DownloadFileButton } from '@components/DownloadFileButton'
import { Can, PERM } from '@shared/permissions'
import { generationImportsApi, type RowState } from '../../api/generationImportsApi'
import type { TemplateRead } from '../../api/templatesApi'
import type { ServerImport } from '../../hooks/useServerImport'
import { GenerationOperationTracker } from './GenerationOperationTracker'
import './generation-operations.css'

const CORE: Array<[string, string]> = [
  ['guest_name', 'اسم الضيف'], ['ticket_class', 'الفئة'], ['guest_count', 'عدد الأشخاص'],
  ['guest_phone', 'الهاتف (دولي)'], ['guest_email', 'البريد'],
]
const STATES: Array<[RowState, string]> = [['all', 'الكل'], ['valid', 'صالحة'], ['invalid', 'بها أخطاء'], ['excluded', 'مستبعدة']]

function RowsTable({ importer }: { importer: ServerImport }) {
  const { upload, revision } = importer.state
  const [state, setState] = useState<RowState>('invalid')
  const [search, setSearch] = useState('')
  const [applied, setApplied] = useState('')
  useEffect(() => { const id = setTimeout(() => setApplied(search.trim()), 350); return () => clearTimeout(id) }, [search])
  const query = useInfiniteQuery({
    queryKey: ['import-rows', upload?.id, revision, state, applied],
    queryFn: ({ pageParam }) => generationImportsApi.rows(upload!.id, { after: pageParam, state, search: applied }),
    initialPageParam: 0,
    getNextPageParam: (last) => last.next_row ?? undefined,
    enabled: !!upload,
  })
  const rows = query.data?.pages.flatMap((p) => p.items) ?? []
  return (
    <div className="gop-log">
      <div className="gop-log__filters" role="group" aria-label="تصفية الصفوف">
        {STATES.map(([k, label]) => (
          <button key={k} type="button" className="inv-dl-btn" aria-pressed={state === k} onClick={() => setState(k)}>{label}</button>
        ))}
        <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="بحث في الصفوف" aria-label="بحث في الصفوف" maxLength={100} />
      </div>
      {query.isLoading ? <p className="gop__hint">جارٍ التحميل…</p> : rows.length === 0 ? <p className="gop__hint">لا توجد صفوف.</p> : (
        <div style={{ overflowX: 'auto' }}>
          <table className="gop-table">
            <thead><tr><th>اختيار</th><th>#</th><th>الاسم</th><th>الفئة</th><th>الأشخاص</th><th>الحالة</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.row_number}>
                  <td>
                    {r.normalized_data && !r.errors.length && !r.excluded && (
                      <input type="checkbox" aria-label={`اختيار الصف ${r.row_number}`}
                        checked={!importer.state.deselected.includes(r.row_number)}
                        onChange={() => importer.toggleRow(r.row_number)} />
                    )}
                  </td>
                  <td>{r.row_number}</td>
                  <td>{r.normalized_data?.guest_name ?? String(Object.values(r.raw_data)[0] ?? '')}</td>
                  <td>{r.normalized_data ? (r.normalized_data.ticket_class === 'vip' ? 'VIP' : 'عادي') : '—'}</td>
                  <td>{r.normalized_data?.guest_count ?? '—'}</td>
                  <td>{r.excluded ? 'صف فارغ' : r.errors.length ? <span className="gop-bad">{r.errors[0]}</span> : 'صالح'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {query.hasNextPage && <button type="button" className="inv-dl-btn" disabled={query.isFetchingNextPage} onClick={() => query.fetchNextPage()}>عرض المزيد</button>}
      {importer.state.deselected.length > 0 && (
        <p className="gop__hint">استبعدت {importer.state.deselected.length} صفًا صالحًا يدويًا.
          <button type="button" className="inv-dl-btn" onClick={importer.selectAllRows}>تحديد الكل</button></p>
      )}
    </div>
  )
}

function Mapping({ importer }: { importer: ServerImport }) {
  const { state } = importer
  const first = useInfiniteQuery({
    queryKey: ['import-headers', state.upload?.id, state.revision],
    queryFn: () => generationImportsApi.rows(state.upload!.id, { state: 'all' }),
    initialPageParam: 0, getNextPageParam: () => undefined, enabled: !!state.upload,
  })
  const headers = Object.keys(first.data?.pages[0]?.items[0]?.raw_data ?? {}).filter((h) => !h.startsWith('__'))
  const [choice, setChoice] = useState<Record<string, string>>({})
  const [custom, setCustom] = useState<Record<string, string>>({})
  const headerSignature = JSON.stringify(headers)
  useEffect(() => {
    const core = new Set(CORE.map(([key]) => key))
    setChoice(Object.fromEntries(Object.entries(state.mapping).filter(([target]) => core.has(target))))
    setCustom(Object.fromEntries(Object.entries(state.mapping).filter(([target, header]) => !core.has(target) && target !== header).map(([target, header]) => [header, target])))
  }, [state.mapping, headerSignature])
  if (!headers.length) return null
  const apply = () => {
    // Chosen columns map to the canonical names; every other column is kept under its own header.
    const chosen = [...Object.entries(choice).filter(([, v]) => v), ...Object.entries(custom).filter(([, v]) => v.trim()).map(([header, target]) => [target.trim(), header])]
    if (new Set(chosen.map(([target]) => target)).size !== chosen.length) { importer.patch({ error: 'مفتاح الحقل مكرر؛ اختر مفتاحاً مختلفاً لكل حقل.' }); return }
    const used = new Set(chosen.map(([, v]) => v))
    if (used.size !== chosen.length) { importer.patch({ error: 'لا يمكن ربط عمودين بالحقل نفسه ولا الحقل بعمودين.' }); return }
    const mapping: Record<string, string> = {}
    headers.filter((h) => !used.has(h)).forEach((h) => { mapping[h] = h })
    chosen.forEach(([target, header]) => { mapping[target] = header })
    void importer.analyze({ mapping })
  }
  return (
    <details className="gop">
      <summary>ربط الأعمدة (اختياري عند اختلاف الأسماء)</summary>
      <div className="gop-map">
        {CORE.map(([target, label]) => (
          <label key={target}>{label}
            <select value={choice[target] ?? ''} onChange={(e) => setChoice((c) => ({ ...c, [target]: e.target.value }))}>
              <option value="">تلقائي</option>
              {headers.map((h) => <option key={h} value={h}>{h}</option>)}
            </select>
          </label>
        ))}
      </div>
      <details><summary>ربط حقول التصميم الإضافية</summary>
        <p className="gop__hint">اكتب مفتاح الحقل كما هو في القالب، مثل guest.company. الأعمدة الأخرى تُحفظ بأسمائها.</p>
        {headers.map(header => <label key={header}>{header}<input value={custom[header] ?? ''} placeholder="مفتاح الحقل في القالب" onChange={e => setCustom(v => ({ ...v, [header]: e.target.value }))} /></label>)}
      </details>
      <button type="button" className="inv-dl-btn" disabled={state.busy} onClick={apply}><RefreshCw size={14} /> إعادة الفحص بهذا الربط</button>
    </details>
  )
}

export function ServerImportPanel({ importer, requireRsvp }: { importer: ServerImport; requireRsvp: boolean }) {
  const { state } = importer
  const input = useRef<HTMLInputElement>(null)
  const s = state.summary
  const stale = !!s && state.analyzedRsvp !== requireRsvp
  return (
    <div className="gop-wrap">
      <div className="gop">
        <div className="gop__title"><FileSpreadsheet size={18} /><strong>استيراد ملف Excel/CSV</strong></div>
        <p className="gop__hint">يُحفظ الملف ويُفحص على الخادم، ولا تُحمَّل الصفوف كلها في المتصفح. الحد 10MB و10,000 صف.</p>
        <input ref={input} type="file" hidden accept=".xlsx,.csv" onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) void importer.chooseFile(f) }} />
        <div className="gop-actions">
          <button type="button" className="inv-dl-btn" disabled={state.busy} onClick={() => input.current?.click()}>
            {state.busy ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />} {state.fileName ? 'استبدال الملف' : 'اختيار ملف'}
          </button>
          {state.fileName && <span className="gop__hint">{state.fileName}</span>}
          {state.upload && <button type="button" className="inv-dl-btn" onClick={importer.reset}>إزالة</button>}
        </div>
        {state.upload && state.upload.sheets.length > 1 && (
          <label>ورقة البيانات
            <select value={state.sheet ?? ''} onChange={(e) => void importer.analyze({ sheet: e.target.value })} disabled={state.busy}>
              {state.upload.sheets.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
        )}
        {state.fileName.toLowerCase().endsWith('.csv') && (
          <label>الفاصل
            <select value={state.delimiter} onChange={(e) => void importer.analyze({ delimiter: e.target.value as ',' | ';' | '\t' })} disabled={state.busy}>
              <option value=",">فاصلة ,</option><option value=";">فاصلة منقوطة ;</option><option value={'\t'}>Tab</option>
            </select>
          </label>
        )}
        {state.error && <p role="alert" className="gop__error"><AlertCircle size={14} /> {state.error}</p>}
      </div>

      {s && (
        <>
          <div className="gop" role="status">
            <strong>نتيجة الفحص</strong>
            <p className="gop__hint">
              {s.total} صف: <b>{s.valid}</b> صالح ({s.vip} VIP · {s.normal} عادي · {s.people} شخص) ·{' '}
              <b className={s.invalid ? 'gop-bad' : ''}>{s.invalid}</b> بها أخطاء · {s.blank} فارغ
            </p>
            {stale && <p role="alert" className="gop__error">تغيّر خيار تأكيد الحضور بعد الفحص. أعد الفحص قبل التوليد.
              <button type="button" className="inv-dl-btn" onClick={() => void importer.analyze()}>إعادة الفحص</button></p>}
            {s.invalid > 0 && (
              <Can permission={PERM.INV_EXPORT}>
                <DownloadFileButton url={generationImportsApi.errorsPath(state.upload!.id)} filename="import-errors.csv" className="inv-dl-btn">تنزيل الصفوف المخالفة لتصحيحها</DownloadFileButton>
              </Can>
            )}
          </div>
          <Mapping importer={importer} />
          <RowsTable importer={importer} />
        </>
      )}
    </div>
  )
}

/** Selection confirmation + generation; rendered after layout/RSVP settings. */
export function ServerImportGenerate({ importer, requireRsvp, layout, designedLayout, templates, formats, maxCards, forceDesigned = false }: {
  importer: ServerImport; requireRsvp: boolean; layout: Record<string, unknown>; designedLayout: Record<string, unknown>
  templates: TemplateRead[]; formats: Array<'pdf' | 'zip'>; maxCards: number; forceDesigned?: boolean
}) {
  const { state } = importer
  const s = state.summary
  const [ack, setAck] = useState(false)
  const [designChoice, setDesigned] = useState(false)
  const designed = forceDesigned || designChoice
  const [chosen, setChosen] = useState<Partial<Record<'vip' | 'normal', string>>>({})
  const exclusions = state.deselected.join(',')
  useEffect(() => { setAck(false) }, [state.revision, exclusions])
  if (state.operation) {
    return <div className="gop-wrap"><GenerationOperationTracker operationId={state.operation.id} />
      <button type="button" className="inv-dl-btn" onClick={importer.reset}>ملف جديد</button></div>
  }
  if (!s) return null
  const manual = state.deselected.length
  const cards = s.valid - manual
  const excluded = s.total - cards
  const stale = state.analyzedRsvp !== requireRsvp
  const tooMany = cards > maxCards
  const classes = (['vip', 'normal'] as const).filter((c) => (c === 'vip' ? s.selected_vip : s.selected_normal))
  const missingTemplate = designed && classes.some((c) => !chosen[c])
  return (
    <div className="gop-wrap">
      {!state.selectionReady ? (
        <div className="gop">
          <p className="gop__hint">سيتم إنشاء <b>{cards}</b> بطاقة{manual === 0 && <> لـ <b>{s.people}</b> شخص</>}{excluded > 0 && <> وسيُستبعد <b className="gop-bad">{excluded}</b> صف</>}.</p>
          {excluded > 0 && (
            <label><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> أفهم أن الصفوف المخالفة أو الفارغة لن تُنشأ لها دعوات</label>
          )}
          {tooMany && <p role="alert" className="gop__error">الحد الحالي {maxCards} دعوة للعملية الواحدة؛ قسّم الملف.</p>}
          <button type="button" className="inv-dl-btn" disabled={state.busy || stale || tooMany || cards <= 0 || (excluded > 0 && !ack)}
            onClick={() => void importer.confirmSelection(excluded > 0 && ack)}>اعتماد الصفوف الصالحة</button>
        </div>
      ) : (
        <div className="gop">
          {!forceDesigned && <div className="gop-actions" role="group" aria-label="نوع المخرجات">
            <button type="button" className="inv-dl-btn" aria-pressed={!designed} onClick={() => setDesigned(false)}>رموز للطباعة</button>
            <button type="button" className="inv-dl-btn" aria-pressed={designed} onClick={() => setDesigned(true)}>كروت مصممة</button>
          </div>}
          {designed && classes.map((c) => (
            <label key={c}>قالب فئة {c === 'vip' ? 'VIP' : 'العادي'} ({c === 'vip' ? s.selected_vip : s.selected_normal} بطاقة)
              <select value={chosen[c] ?? ''} onChange={(e) => setChosen((v) => ({ ...v, [c]: e.target.value || undefined }))}>
                <option value="">اختر قالبًا</option>
                {templates.filter((tpl) => tpl.template_type === 'designed' && tpl.ticket_class === c && tpl.is_active).map((tpl) => <option key={tpl.id} value={tpl.id}>{tpl.name}</option>)}
              </select>
            </label>
          ))}
          <p className="gop__hint">اعتُمد اختيار {s.selected} صف. {formats.length === 0 ? 'ستُنشأ الدعوات دون ملفات (لا تملك صلاحية التصدير).' : 'ستُنشأ الدعوات وملفات الطباعة.'}</p>
          <button type="button" className="inv-generate-btn" disabled={state.busy || stale || missingTemplate}
            onClick={() => void (designed
              ? importer.generate({ mode: 'designed', templates: Object.fromEntries(classes.map(c => [c, chosen[c]])), layout: designedLayout, formats })
              : importer.generate({ layout: { ...layout, show_code_text: false, show_guest_name: false }, formats }))}>
            {state.busy ? <><Loader2 size={18} className="animate-spin" /> جارٍ القبول…</> : `بدء التوليد (${s.selected} بطاقة)`}
          </button>
          <p className="gop__hint">بعد القبول تُتابَع العملية ويمكنك مغادرة الصفحة.</p>
        </div>
      )}
      {state.error && <p role="alert" className="gop__error">{state.error}</p>}
    </div>
  )
}
