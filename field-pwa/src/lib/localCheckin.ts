import type { FieldCheckinResult, OfflinePack, QueuedCheckin } from '../domain'

async function sha256(value: string): Promise<string> {
  const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value))
  return Array.from(new Uint8Array(bytes), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

function normalizeLocal(raw: string): string | null {
  const value = raw.trim()
  const qentry = /^qentry:v1:[0-9a-f-]{36}:([A-Za-z0-9_-]{8,512}):[0-9a-f]{32}$/i.exec(value)
  if (qentry) return qentry[1]
  const signed = /^[0-9a-f-]{36}:([A-Za-z0-9_-]{8,512}):[0-9a-f]{32}$/i.exec(value)
  if (signed) return signed[1]
  const url = /^https?:\/\/[^/]+\/i\/([A-Za-z0-9_-]{8,512})\/?$/i.exec(value)
  if (url) return url[1]
  return /^[A-Za-z0-9_-]{8,512}$/.test(value) ? value : null
}

function localResult(result: string, message: string, entryCount: number, needsHelp: boolean, item?: OfflinePack['items'][number]): FieldCheckinResult {
  return { result, message, invitation_id: null, guest_name: null, ticket_class: item?.ticket_class || null,
    event_title: null, checkin_count: 0, guest_count: item?.allowed_count || 0,
    remaining_count: item?.remaining_count || 0, entry_count: entryCount,
    requires_assistance: needsHelp, code_format: 'offline_pack', idempotent: false }
}

export async function localCheckin(pack: OfflinePack, rawCode: string, entryCount: number): Promise<FieldCheckinResult> {
  if (new Date(pack.valid_until).getTime() <= Date.now()) return localResult('pack_invalid', 'انتهت حزمة العمل. اتصل بالخادم قبل المتابعة.', entryCount, true)
  const normalized = normalizeLocal(rawCode)
  if (!normalized) return localResult('invalid', 'رمز الدعوة غير صالح في حزمة العمل.', entryCount, true)
  const fingerprint = await sha256(`${pack.fingerprint_salt}:${normalized}`)
  const item = pack.items.find((candidate) => candidate.code_fingerprint === fingerprint)
  if (!item) return localResult('invalid', 'هذه الدعوة لا تنتمي إلى حزمة هذه البوابة.', entryCount, true)
  if (item.expires_at && new Date(item.expires_at).getTime() < Date.now()) return localResult('expired', 'انتهت صلاحية الدعوة.', entryCount, true, item)
  if (entryCount > item.remaining_count) return localResult(item.remaining_count === 0 ? 'already_checked_in' : 'capacity_exceeded', 'العدد المطلوب أكبر من المتبقي في الدعوة.', entryCount, true, item)
  item.remaining_count -= entryCount
  return { result: 'success', message: 'تم قبول الدعوة محلياً وستتم مزامنتها عند عودة الشبكة.', invitation_id: null,
    guest_name: null, ticket_class: item.ticket_class, event_title: null, checkin_count: 0,
    guest_count: item.allowed_count, remaining_count: item.remaining_count, entry_count: entryCount,
    requires_assistance: false, code_format: 'offline_pack', idempotent: false }
}

export function queuedItem(rawCode: string, entryCount: number, pack: OfflinePack, scanMethod: QueuedCheckin['scan_method']): QueuedCheckin {
  return { client_scan_id: crypto.randomUUID(), captured_at: new Date().toISOString(), raw_code: rawCode,
    entry_count: entryCount, pack_version: pack.version, scan_method: scanMethod }
}
