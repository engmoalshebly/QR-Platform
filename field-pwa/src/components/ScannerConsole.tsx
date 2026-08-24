import { useCallback, useEffect, useState } from 'react'
import type { DeviceSession, FieldCheckinResult, FieldSearchResult, OfflinePack } from '../domain'
import { ApiError, fieldApi } from '../lib/api'
import { localCheckin, queuedItem } from '../lib/localCheckin'
import { offlineStore } from '../lib/offlineStore'
import { CameraScanner } from './CameraScanner'

type ScanMethod = 'camera' | 'manual' | 'code128'
type HistoryEntry = Pick<FieldCheckinResult, 'result' | 'message' | 'entry_count' | 'remaining_count'> & { at: string; offline: boolean }

function errorText(error: unknown) { return error instanceof Error ? error.message : 'حدث خطأ غير متوقع.' }
function resultLabel(result: string) {
  return ({ success: 'تم القبول', invalid: 'رمز غير صالح', revoked: 'دعوة ملغاة', expired: 'دعوة منتهية', wrong_gate: 'بوابة غير مسموحة', wrong_event: 'حفل مختلف', registration_code: 'رمز تسجيل عام', already_checked_in: 'دعوة مستخدمة', capacity_exceeded: 'عدد أكبر من المتبقي', offline_conflict: 'تعارض دون اتصال', pack_invalid: 'الحزمة غير صالحة', processing: 'جارٍ المعالجة' } as Record<string, string>)[result] || 'تحتاج مراجعة'
}
function assistanceType(result: FieldCheckinResult | null): 'duplicate' | 'manual_confirmation' | 'access' | 'device' | 'offline_conflict' | 'other' {
  if (result?.result === 'already_checked_in') return 'duplicate'
  if (result?.result === 'offline_conflict') return 'offline_conflict'
  if (result?.result === 'wrong_gate' || result?.result === 'wrong_event') return 'access'
  return 'manual_confirmation'
}
function notifyResult(result: FieldCheckinResult) {
  navigator.vibrate?.(result.result === 'success' ? [55, 40, 70] : [130, 55, 130])
  try {
    const AudioContextClass = window.AudioContext || (window as Window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!AudioContextClass) return
    const context = new AudioContextClass(); const oscillator = context.createOscillator(); const gain = context.createGain()
    oscillator.frequency.value = result.result === 'success' ? 880 : 210
    gain.gain.setValueAtTime(0.08, context.currentTime); gain.gain.exponentialRampToValueAtTime(0.001, context.currentTime + 0.18)
    oscillator.connect(gain).connect(context.destination); oscillator.start(); oscillator.stop(context.currentTime + 0.18)
  } catch { /* Feedback is optional and never changes the access decision. */ }
}

export function ScannerConsole({ session, online, onClose, closing, closeError }: { session: DeviceSession; online: boolean; onClose: () => void; closing: boolean; closeError: string | null }) {
  const [pack, setPack] = useState<OfflinePack | null>(null)
  const [packState, setPackState] = useState<'loading' | 'ready' | 'unavailable'>('loading')
  const [queueCount, setQueueCount] = useState(0)
  const [result, setResult] = useState<FieldCheckinResult | null>(null)
  const [history, setHistory] = useState<HistoryEntry[]>([])
  const [busy, setBusy] = useState(false)
  const [scannerError, setScannerError] = useState<string | null>(null)
  const [manualOpen, setManualOpen] = useState(false)
  const [manualCode, setManualCode] = useState('')
  const [searchTerm, setSearchTerm] = useState('')
  const [searchItems, setSearchItems] = useState<FieldSearchResult[]>([])
  const [searchError, setSearchError] = useState<string | null>(null)
  const [searching, setSearching] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [helpSent, setHelpSent] = useState(false)
  const [lastScan, setLastScan] = useState<{ code: string; method: ScanMethod } | null>(null)
  const [additionalCount, setAdditionalCount] = useState(1)

  const refreshQueue = useCallback(async (activePack: OfflinePack | null) => {
    if (!activePack) { setQueueCount(0); return }
    try { setQueueCount((await offlineStore.queued(activePack.pack_id)).length) } catch { setPackState('unavailable') }
  }, [])
  const downloadPack = useCallback(async () => {
    if (!online) return
    setPackState('loading')
    try { const next = await fieldApi.downloadPack(session.shift_id); await offlineStore.savePack(session.id, next); setPack(next); setPackState('ready'); await refreshQueue(next) }
    catch { setPackState('unavailable') }
  }, [online, refreshQueue, session.shift_id])
  useEffect(() => {
    // A persistent session key gives an installed PWA the same encrypted pack
    // after a reload. It is never a guest list and expires with the server
    // session; the online path still refreshes the canonical pack.
    let cancelled = false
    void offlineStore.getPack(session.id).then((stored) => {
      if (!cancelled && stored?.pack) {
        setPack(stored.pack)
        setPackState('ready')
        void refreshQueue(stored.pack)
      }
    }).catch(() => { if (!cancelled) setPackState('unavailable') })
    if (online) void downloadPack()
    return () => { cancelled = true }
  }, [downloadPack, online, refreshQueue, session.id])
  const appendResult = useCallback((next: FieldCheckinResult, offline: boolean) => { setResult(next); setHelpSent(false); setAdditionalCount(1); notifyResult(next); setHistory((current) => [{ result: next.result, message: next.message, entry_count: next.entry_count, remaining_count: next.remaining_count, at: new Date().toISOString(), offline }, ...current].slice(0, 8)) }, [])

  const submitOffline = useCallback(async (rawCode: string, entryCount: number, method: ScanMethod) => {
    if (!pack) { appendResult({ result: 'pack_invalid', message: 'لا توجد حزمة عمل محلية صالحة. اتصل بالخادم قبل المسح.', invitation_id: null, guest_name: null, ticket_class: null, event_title: null, checkin_count: 0, guest_count: 0, remaining_count: 0, entry_count: entryCount, requires_assistance: true, code_format: null, idempotent: false }, true); return }
    const local = await localCheckin(pack, rawCode, entryCount)
    if (local.result === 'success') { const queued = queuedItem(rawCode, entryCount, pack, method); await offlineStore.savePack(session.id, pack); await offlineStore.queue(pack.pack_id, queued); await refreshQueue(pack) }
    appendResult(local, true)
  }, [appendResult, pack, refreshQueue])

  const scan = useCallback(async (rawCode: string, method: ScanMethod, entryCount = 1) => {
    if (busy || !rawCode.trim()) return
    setBusy(true); setScannerError(null); setManualOpen(false); setLastScan({ code: rawCode, method })
    try {
      if (!online) { await submitOffline(rawCode, entryCount, method); return }
      const next = await fieldApi.checkin({ raw_code: rawCode, entry_count: entryCount, client_scan_id: crypto.randomUUID(), client_captured_at: new Date().toISOString(), scan_method: method })
      appendResult(next, false)
    } catch (error) {
      if (error instanceof ApiError && error.status === 0) await submitOffline(rawCode, entryCount, method)
      else setScannerError(errorText(error))
    } finally { setBusy(false) }
  }, [appendResult, busy, online, submitOffline])

  const syncQueue = useCallback(async () => {
    if (!pack || !online || syncing) return
    setSyncing(true)
    try { const queued = await offlineStore.queued(pack.pack_id); if (!queued.length) return; const response = await fieldApi.syncCheckins(pack.pack_id, queued); await offlineStore.removeQueued(pack.pack_id, queued.map((item) => item.client_scan_id)); await refreshQueue(pack); response.results.forEach((item) => appendResult(item, false)) }
    catch (error) { setScannerError(errorText(error)) } finally { setSyncing(false) }
  }, [appendResult, online, pack, refreshQueue, syncing])
  useEffect(() => { if (online && queueCount) void syncQueue() }, [online, queueCount, syncQueue])

  const search = async () => { if (searchTerm.trim().length < 2) { setSearchError('اكتب حرفين على الأقل للبحث.'); return }; setSearching(true); setSearchError(null); try { setSearchItems(await fieldApi.searchInvitations(searchTerm.trim())) } catch (error) { setSearchError(errorText(error)) } finally { setSearching(false) } }
  const manualConfirm = async (invitationId: string) => { if (!online || busy) return; setBusy(true); setSearchError(null); try { const next = await fieldApi.checkin({ invitation_id: invitationId, entry_count: 1, client_scan_id: crypto.randomUUID(), client_captured_at: new Date().toISOString(), scan_method: 'manual' }); appendResult(next, false); setManualOpen(false) } catch (error) { setSearchError(errorText(error)) } finally { setBusy(false) } }
  const askSupervisor = async () => { if (!result || !online || helpSent) return; try { await fieldApi.requestAssistance({ assistance_type: assistanceType(result), note: `نتيجة المسح: ${result.result}` }); setHelpSent(true) } catch (error) { setScannerError(errorText(error)) } }
  const resultTone = result?.result === 'success' ? 'accepted' : result?.requires_assistance ? 'warning' : 'rejected'
  const canAddGroup = Boolean(result?.result === 'success' && lastScan && result.remaining_count > 0 && result.guest_count > result.entry_count)

  const hasPendingSync = queueCount > 0
  return <main className="field-shell scanner-page"><header className="app-header"><div><span className="eyebrow">جلسة بوابة نشطة</span><h1>{session.device_name || 'جهاز البوابة'}</h1></div><span className={online ? 'network online' : 'network offline'}>{online ? 'متصل' : 'دون اتصال'}</span></header><section className="scanner-summary"><div><span>بوابة مخصصة</span><strong className="mono">{session.gate_id.slice(0, 8)}</strong></div><div><span>حزمة العمل</span><strong>{packState === 'ready' ? 'جاهزة' : packState === 'loading' ? 'جارٍ التنزيل' : 'غير متاحة'}</strong></div><div><span>بانتظار المزامنة</span><strong>{queueCount}</strong></div></section>{scannerError && <p className="error-note" role="alert">{scannerError}</p>}{result ? <section className={`scan-result scan-result--${resultTone}`} aria-live="assertive" role="status"><span className="result-icon" aria-hidden="true">{resultTone === 'accepted' ? '✓' : resultTone === 'warning' ? '!' : '×'}</span><p className="result-kicker">{resultLabel(result.result)}</p><h2>{result.message}</h2>{online && result.guest_name && <p className="guest-name">{result.guest_name}</p>}<dl><div><dt>الفئة</dt><dd>{result.ticket_class || '—'}</dd></div><div><dt>المتبقي</dt><dd>{result.remaining_count}</dd></div><div><dt>المسجل الآن</dt><dd>{result.entry_count}</dd></div></dl>{canAddGroup && <div className="group-entry"><label>إضافة أفراد من الدعوة نفسها<select value={additionalCount} onChange={(event) => setAdditionalCount(Number(event.target.value))}>{Array.from({ length: result.remaining_count }, (_, index) => index + 1).map((count) => <option key={count} value={count}>{count} شخص</option>)}</select></label><button className="secondary-button" disabled={busy} onClick={() => lastScan && void scan(lastScan.code, lastScan.method, additionalCount)}>تسجيل العدد الإضافي</button></div>}{result.requires_assistance && <button className="warning-button" disabled={!online || helpSent} onClick={() => void askSupervisor()}>{helpSent ? 'تم إرسال طلب المساعدة' : online ? 'استدعاء مشرف البوابة' : 'يتطلب الاتصال لاستدعاء المشرف'}</button>}<button className="primary-button" onClick={() => { setResult(null); setLastScan(null) }}>مسح دعوة أخرى</button></section> : <section className="scan-stage"><CameraScanner active={!manualOpen && !busy} onCode={(code, method) => void scan(code, method)} onError={setScannerError} /><div className="scan-tools"><button className="secondary-button" onClick={() => setManualOpen((value) => !value)}>بحث أو إدخال يدوي</button><button className="text-button" disabled={!online || packState === 'loading'} onClick={() => void downloadPack()}>تحديث حزمة العمل</button></div></section>}{manualOpen && <section className="manual-panel"><div className="section-heading"><h2>بحث يدوي محدود</h2><button className="text-button" onClick={() => setManualOpen(false)}>إغلاق</button></div>{!online && <p className="error-note">البحث اليدوي يحتاج اتصالاً ولا يعرض بيانات من الحزمة المحلية.</p>}<div className="manual-form"><input value={searchTerm} onChange={(event) => setSearchTerm(event.target.value)} placeholder="الاسم أو المقعد أو الطاولة" /><button className="secondary-button" disabled={!online || searching} onClick={() => void search()}>{searching ? 'جارٍ البحث…' : 'بحث'}</button></div>{searchError && <p className="error-note">{searchError}</p>}{searchItems.map((item) => <article className="search-item" key={item.id}><div><strong>{item.label}</strong><span>{item.ticket_class} · متبقي {item.remaining_count} من {item.guest_count}</span></div><button className="primary-button" disabled={busy || item.remaining_count < 1} onClick={() => void manualConfirm(item.id)}>تأكيد دخول واحد</button></article>)}<div className="paste-code"><label>إدخال رمز الدعوة عند تعذر القراءة<input value={manualCode} onChange={(event) => setManualCode(event.target.value)} placeholder="ألصق الرمز هنا" /></label><button className="text-button" disabled={!manualCode.trim()} onClick={() => void scan(manualCode, 'manual')}>تحقق من الرمز</button></div></section>}<section className="sync-panel"><div><span className="eyebrow">حالة الشبكة والمزامنة</span><h2>{queueCount ? `${queueCount} عملية تنتظر المزامنة` : 'كل العمليات متزامنة'}</h2><p>الحزمة لا تحتوي اسماً أو هاتفاً أو بريداً. القرار النهائي للحضور يصدر من الخادم عند المزامنة.</p></div><button className="secondary-button" disabled={!online || !pack || !queueCount || syncing} onClick={() => void syncQueue()}>{syncing ? 'جارٍ المزامنة…' : 'مزامنة الآن'}</button></section>{history.length > 0 && <section className="recent-scans"><h2>آخر العمليات على هذا الجهاز</h2>{history.map((item, index) => <div key={`${item.at}-${index}`}><span className={`history-dot history-dot--${item.result === 'success' ? 'accepted' : 'rejected'}`} /><strong>{resultLabel(item.result)}</strong><small>{item.offline ? 'محلياً' : 'متصل'} · {item.entry_count} شخص</small></div>)}</section>}{hasPendingSync && <p className="error-note">زامن {queueCount} عملية قبل إنهاء الجلسة وتسليم البوابة.</p>}<button className="danger-button scanner-close" disabled={closing || hasPendingSync} onClick={onClose}>{closing ? 'جارٍ إنهاء الجلسة…' : hasPendingSync ? 'تتطلب الجلسة مزامنة أولاً' : 'إنهاء الجلسة وتسليم البوابة'}</button>{closeError && <p className="error-note">{closeError}</p>}</main>
}
