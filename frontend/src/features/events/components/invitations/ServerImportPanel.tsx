import { useEffect, useRef, useState } from 'react'
import { useInfiniteQuery } from '@tanstack/react-query'
import { AlertCircle, Download, FileSpreadsheet, Loader2, RefreshCw, Upload } from 'lucide-react'
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
/** A per-guest field the chosen design prints (event fields are excluded). */
export type DesignField = { key: string; label: string }
const norm = (v: string) => v.trim().toLowerCase().replace(/[\s_\-.]+/g, '').replace(/[أإآ]/g, 'ا').replace(/ة/g, 'ه').replace(/ى/g, 'ي')
const CORE_KEYS = new Set(['اسمالضيف', 'guestname', 'name', 'guestname', 'عددالاشخاص', 'عددالدعوات', 'guestcount', 'نوعالتذكره', 'الفئه', 'ticketclass'])
export const designFieldsOf = (fields: Array<{ data_key: string; label: string; element_type?: string }>): DesignField[] => {
  const seen = new Set<string>()
  return fields
    .filter(f => f.data_key && !/^(event|invite)\./.test(f.data_key) && f.element_type !== 'qr_code' && !CORE_KEYS.has(norm(f.data_key)))
    .filter(f => !seen.has(f.data_key) && !!seen.add(f.data_key))
    .map(f => ({ key: f.data_key, label: f.label || f.data_key }))
}
/** Column a design field reads: the explicit mapping, else a header with the same name. */
const headerFor = (field: DesignField, headers: string[], mapping: Record<string, string>) =>
  (mapping[field.key] && field.key !== mapping[field.key] ? mapping[field.key] : undefined)
  ?? headers.find(h => norm(h) === norm(field.key) || norm(h) === norm(field.label))

const STATES: Array<[RowState, string]> = [['all', 'الكل'], ['valid', 'صالحة'], ['invalid', 'بها أخطاء'], ['excluded', 'مستبعدة']]

function RowsTable({ importer, columns = [] }: { importer: ServerImport; columns?: Array<{ label: string; header?: string }> }) {
  const { upload, revision } = importer.state
  const hasErrors = (importer.state.summary?.invalid ?? 0) > 0
  const [state, setState] = useState<RowState>(hasErrors ? 'invalid' : 'all')
  useEffect(() => { setState(hasErrors ? 'invalid' : 'all') }, [hasErrors, upload?.id])
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
    <div className="gop-log gim-rows">
      <div className="gim-rows__head">
      <strong>قائمة الضيوف</strong>
      {hasErrors && <div className="gop-log__filters" role="group" aria-label="تصفية الصفوف">
        {STATES.map(([k, label]) => (
          <button key={k} type="button" className="inv-dl-btn" aria-pressed={state === k} onClick={() => setState(k)}>{label}</button>
        ))}
      </div>}
        <input className="gim-search" type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="بحث بالاسم" aria-label="بحث في الصفوف" maxLength={100} />
      </div>
      {query.isLoading ? <p className="gop__hint">جارٍ التحميل…</p> : rows.length === 0 ? <p className="gop__hint">لا توجد صفوف.</p> : (
        <div style={{ overflowX: 'auto' }}>
          <table className="gop-table">
            <thead><tr><th>اختيار</th><th>#</th><th>الاسم</th><th>الفئة</th><th>الأشخاص</th>{columns.map(c => <th key={c.label}>{c.label}</th>)}<th>الحالة</th></tr></thead>
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
                  {columns.map(c => <td key={c.label}>{c.header ? String(r.raw_data[c.header] ?? '') || '—' : <span className="gop-bad">—</span>}</td>)}
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

function Mapping({ importer, hideDesignKeys = false }: { importer: ServerImport; hideDesignKeys?: boolean }) {
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
      <summary>ربط الأعمدة الأساسية (عند اختلاف أسماء الأعمدة عن النموذج)</summary>
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
      {!hideDesignKeys && <details><summary>ربط حقول التصميم الإضافية</summary>
        <p className="gop__hint">اكتب مفتاح الحقل كما هو في القالب، مثل guest.company. الأعمدة الأخرى تُحفظ بأسمائها.</p>
        {headers.map(header => <label key={header}>{header}<input value={custom[header] ?? ''} placeholder="مفتاح الحقل في القالب" onChange={e => setCustom(v => ({ ...v, [header]: e.target.value }))} /></label>)}
      </details>}
      <button type="button" className="inv-dl-btn" disabled={state.busy} onClick={apply}><RefreshCw size={14} /> إعادة الفحص بهذا الربط</button>
    </details>
  )
}

function useHeaders(importer: ServerImport) {
  const { state } = importer
  const first = useInfiniteQuery({
    queryKey: ['import-headers', state.upload?.id, state.revision],
    queryFn: () => generationImportsApi.rows(state.upload!.id, { state: 'all' }),
    initialPageParam: 0, getNextPageParam: () => undefined, enabled: !!state.upload,
  })
  return Object.keys(first.data?.pages[0]?.items[0]?.raw_data ?? {}).filter((h) => !h.startsWith('__'))
}

/** Which file column fills each field of the chosen design; matched by name automatically. */
function DesignFieldMapping({ importer, fields, headers }: { importer: ServerImport; fields: DesignField[]; headers: string[] }) {
  const { state } = importer
  const [choice, setChoice] = useState<Record<string, string>>({})
  const signature = JSON.stringify([headers, state.mapping, fields])
  useEffect(() => {
    setChoice(Object.fromEntries(fields.map(f => [f.key, headerFor(f, headers, state.mapping) ?? ''])))
  }, [signature])
  if (!fields.length || !headers.length) return null
  const missing = fields.filter(f => !choice[f.key])
  const changed = fields.some(f => (choice[f.key] || '') !== (headerFor(f, headers, state.mapping) ?? ''))
  const apply = () => {
    const picked = fields.filter(f => choice[f.key])
    const used = picked.map(f => choice[f.key])
    if (new Set(used).size !== used.length) { importer.patch({ error: 'لا يمكن ربط عمود واحد بحقلين في التصميم.' }); return }
    // Core columns keep their mapping; each design field reads its chosen column.
    const mapping: Record<string, string> = Object.fromEntries(Object.entries(state.mapping).filter(([target, header]) => !used.includes(header) && !fields.some(f => f.key === target)))
    headers.filter(h => !used.includes(h) && !Object.values(mapping).includes(h)).forEach(h => { mapping[h] = h })
    picked.forEach(f => { mapping[f.key] = choice[f.key] })
    void importer.analyze({ mapping })
  }
  return (
    <div className="gop">
      <strong>حقول التصميم</strong>
      <p className="gop__hint">ربطنا كل حقل في القالب بالعمود الذي يحمل نفس الاسم في ملفك. غيّر الربط إن لزم.</p>
      <div className="gop-map">
        {fields.map(f => (
          <label key={f.key}>{f.label}
            <select value={choice[f.key] ?? ''} onChange={(e) => setChoice(c => ({ ...c, [f.key]: e.target.value }))} disabled={state.busy}>
              <option value="">— لا يوجد عمود (يُطبع فارغاً) —</option>
              {headers.map(h => <option key={h} value={h}>{h}</option>)}
            </select>
          </label>
        ))}
      </div>
      {missing.length > 0 && <p role="alert" className="gop__error"><AlertCircle size={14} /> {missing.map(f => f.label).join('، ')}: لا يوجد عمود مطابق في الملف، سيُطبع فارغاً.</p>}
      {changed && <button type="button" className="inv-dl-btn" disabled={state.busy} onClick={apply}><RefreshCw size={14} /> تطبيق الربط وإعادة الفحص</button>}
    </div>
  )
}

export function ServerImportPanel({ importer, requireRsvp, onDownloadTemplate, designFields }: { importer: ServerImport; requireRsvp: boolean; onDownloadTemplate?: () => Promise<void>; designFields?: DesignField[] }) {
  const headers = useHeaders(importer)
  const { state } = importer
  const input = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const s = state.summary
  const stale = !!s && state.analyzedRsvp !== requireRsvp
  const pick = (f?: File | null) => { if (f) void importer.chooseFile(f) }
  const isCsv = state.fileName.toLowerCase().endsWith('.csv')
  const hasOptions = !!state.upload && (state.upload.sheets.length > 1 || isCsv)
  return (
    <div className="gim">
      <input ref={input} type="file" hidden accept=".xlsx,.csv" onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; pick(f) }} />

      {!state.upload ? (
        <>
          <button
            type="button"
            className={`gim-drop${dragging ? ' is-over' : ''}`}
            disabled={state.busy}
            onClick={() => input.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files?.[0]) }}
          >
            {state.busy ? <Loader2 size={30} className="animate-spin" /> : <Upload size={30} />}
            <strong>{state.busy ? 'جارٍ رفع الملف وفحصه…' : 'اسحب ملف الضيوف هنا أو اضغط للاختيار'}</strong>
            <span>Excel أو CSV · حتى 10,000 ضيف</span>
          </button>
          {onDownloadTemplate && (
            <p className="gim-template">
              <FileSpreadsheet size={15} /> ليس لديك ملف؟
              <button type="button" onClick={() => { void onDownloadTemplate() }}><Download size={14} /> نزّل نموذج الضيوف</button>
              واملأه ثم ارفعه.
            </p>
          )}
        </>
      ) : (
        <div className="gim-file">
          <FileSpreadsheet size={22} />
          <div className="gim-file__name">
            <strong>{state.fileName}</strong>
            <span>{state.busy ? 'جارٍ الفحص…' : s ? `${s.total} صف` : 'تم الرفع'}</span>
          </div>
          <button type="button" className="inv-dl-btn" disabled={state.busy} onClick={() => input.current?.click()}><RefreshCw size={14} /> استبدال</button>
          <button type="button" className="inv-dl-btn" disabled={state.busy} onClick={importer.reset}>إزالة</button>
        </div>
      )}

      {state.error && <p role="alert" className="gop__error"><AlertCircle size={14} /> {state.error}</p>}

      {s && (
        <>
          <div className="gim-stats" role="status">
            <div className="gim-stat gim-stat--ok"><strong>{s.valid}</strong><span>ضيف جاهز</span></div>
            <div className="gim-stat"><strong>{s.people}</strong><span>شخص</span></div>
            <div className="gim-stat"><strong>{s.normal}<small> عادي</small> · {s.vip}<small> VIP</small></strong><span>الفئات</span></div>
            <div className={`gim-stat${s.invalid ? ' gim-stat--bad' : ''}`}><strong>{s.invalid}</strong><span>بها أخطاء</span></div>
          </div>

          {stale && <p role="alert" className="gop__error">تغيّر خيار تأكيد الحضور بعد الفحص.
            <button type="button" className="inv-dl-btn" onClick={() => void importer.analyze()}>إعادة الفحص</button></p>}

          {s.invalid > 0 && (
            <div className="gim-alert">
              <AlertCircle size={16} />
              <span>{s.invalid} صف لن تُنشأ لهم دعوات حتى تُصحَّح.</span>
              <Can permission={PERM.INV_EXPORT}>
                <DownloadFileButton url={generationImportsApi.errorsPath(state.upload!.id)} filename="import-errors.csv" className="inv-dl-btn">تنزيل الصفوف المخالفة</DownloadFileButton>
              </Can>
            </div>
          )}

          {designFields && <DesignFieldMapping importer={importer} fields={designFields} headers={headers} />}

          <RowsTable importer={importer} columns={(designFields ?? []).map(f => ({ label: f.label, header: headerFor(f, headers, state.mapping) }))} />

          <details className="gim-advanced">
            <summary>خيارات متقدمة: ربط الأعمدة{hasOptions ? ' وورقة البيانات' : ''}</summary>
            {state.upload!.sheets.length > 1 && (
              <label>ورقة البيانات
                <select value={state.sheet ?? ''} onChange={(e) => void importer.analyze({ sheet: e.target.value })} disabled={state.busy}>
                  {state.upload!.sheets.map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
              </label>
            )}
            {isCsv && (
              <label>الفاصل
                <select value={state.delimiter} onChange={(e) => void importer.analyze({ delimiter: e.target.value as ',' | ';' | '\t' })} disabled={state.busy}>
                  <option value=",">فاصلة ,</option><option value=";">فاصلة منقوطة ;</option><option value={'\t'}>Tab</option>
                </select>
              </label>
            )}
            <Mapping importer={importer} hideDesignKeys={!!designFields} />
          </details>
        </>
      )}
    </div>
  )
}

/** Selection confirmation + generation; rendered after layout/RSVP settings. */
export function ServerImportGenerate({ importer, requireRsvp, layout, designedLayout, templates, formats, maxCards, forceDesigned = false, presetTemplates }: {
  importer: ServerImport; requireRsvp: boolean; layout: Record<string, unknown>; designedLayout: Record<string, unknown>
  templates: TemplateRead[]; formats: Array<'pdf' | 'zip'>; maxCards: number; forceDesigned?: boolean
  /** Template already chosen before the upload, per guest class. */
  presetTemplates?: Partial<Record<'vip' | 'normal', string>>
}) {
  const { state } = importer
  const s = state.summary
  const [ack, setAck] = useState(false)
  const [designChoice, setDesigned] = useState(false)
  const designed = forceDesigned || designChoice
  const [chosen, setChosen] = useState<Partial<Record<'vip' | 'normal', string>>>(presetTemplates ?? {})
  const presetKey = JSON.stringify(presetTemplates ?? {})
  useEffect(() => { if (presetTemplates) setChosen(v => ({ ...v, ...presetTemplates })) }, [presetKey])
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
          <button type="button" className="inv-generate-btn" disabled={state.busy || stale || tooMany || cards <= 0 || (excluded > 0 && !ack)}
            onClick={() => void importer.confirmSelection(excluded > 0 && ack)}>متابعة ({cards} ضيف)</button>
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
            {state.busy ? <><Loader2 size={18} className="animate-spin" /> جارٍ القبول…</> : `إنشاء الدعوات (${s.selected} بطاقة)`}
          </button>
          <p className="gop__hint">بعد القبول تُتابَع العملية ويمكنك مغادرة الصفحة.</p>
        </div>
      )}
      {state.error && <p role="alert" className="gop__error">{state.error}</p>}
    </div>
  )
}
