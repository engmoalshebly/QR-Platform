import type { OfflinePack, QueuedCheckin, StoredFieldSession } from '../domain'

const DB_NAME = 'qentry-field-secure-v1'
const DB_VERSION = 2
const PACK_STORE = 'packs'
const QUEUE_STORE = 'queue'
const KEY_STORE = 'keys'
const SESSION_STORE = 'sessions'

interface SecureRecord { id: string; iv: ArrayBuffer; payload: ArrayBuffer; updatedAt: string }
interface StoredPack { pack: OfflinePack; downloadedAt: string }
interface StoredSession { session: StoredFieldSession; userId: string }
interface KeyRecord { id: string; key: CryptoKey }

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION)
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains(PACK_STORE)) db.createObjectStore(PACK_STORE, { keyPath: 'id' })
      if (!db.objectStoreNames.contains(QUEUE_STORE)) db.createObjectStore(QUEUE_STORE, { keyPath: 'id' })
      if (!db.objectStoreNames.contains(KEY_STORE)) db.createObjectStore(KEY_STORE, { keyPath: 'id' })
      if (!db.objectStoreNames.contains(SESSION_STORE)) db.createObjectStore(SESSION_STORE, { keyPath: 'id' })
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

function tx<T>(storeName: string, mode: IDBTransactionMode, work: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return openDb().then((db) => new Promise<T>((resolve, reject) => {
    const transaction = db.transaction(storeName, mode)
    const request = work(transaction.objectStore(storeName))
    let value: T
    request.onsuccess = () => { value = request.result }
    request.onerror = () => { db.close(); reject(request.error) }
    transaction.oncomplete = () => { db.close(); resolve(value!) }
    transaction.onerror = () => { db.close(); reject(transaction.error) }
    transaction.onabort = () => { db.close(); reject(transaction.error || request.error) }
  }))
}

async function deviceKey(): Promise<CryptoKey> {
  const stored = await tx<KeyRecord | undefined>(KEY_STORE, 'readonly', (store) => store.get('device-key'))
  if (stored?.key) return stored.key
  const key = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt'])
  await tx<IDBValidKey>(KEY_STORE, 'readwrite', (store) => store.put({ id: 'device-key', key }))
  return key
}

async function encrypt(value: unknown): Promise<Pick<SecureRecord, 'iv' | 'payload'>> {
  const iv = crypto.getRandomValues(new Uint8Array(12))
  const plaintext = new TextEncoder().encode(JSON.stringify(value))
  const payload = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, await deviceKey(), plaintext)
  return { iv: iv.buffer, payload }
}

async function decrypt<T>(record: SecureRecord): Promise<T> {
  const plaintext = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: record.iv }, await deviceKey(), record.payload)
  return JSON.parse(new TextDecoder().decode(plaintext)) as T
}

async function putEncrypted(store: string, id: string, value: unknown) {
  const encrypted = await encrypt(value)
  await tx<IDBValidKey>(store, 'readwrite', (objectStore) => objectStore.put({ id, ...encrypted, updatedAt: new Date().toISOString() }))
}

async function getEncrypted<T>(store: string, id: string): Promise<T | null> {
  const record = await tx<SecureRecord | undefined>(store, 'readonly', (objectStore) => objectStore.get(id))
  return record ? decrypt<T>(record) : null
}

export const offlineStore = {
  async savePack(deviceSessionId: string, pack: OfflinePack) { await putEncrypted(PACK_STORE, deviceSessionId, { pack, downloadedAt: new Date().toISOString() } satisfies StoredPack) },
  async getPack(deviceSessionId: string) { return getEncrypted<StoredPack>(PACK_STORE, deviceSessionId) },
  async queue(packId: string, item: QueuedCheckin) { await putEncrypted(QUEUE_STORE, `${packId}:${item.client_scan_id}`, { packId, item }) },
  async queued(packId: string) {
    const records = await tx<SecureRecord[]>(QUEUE_STORE, 'readonly', (store) => store.getAll())
    const decoded = await Promise.all(records.map((record) => decrypt<{ packId: string; item: QueuedCheckin }>(record)))
    return decoded.filter((record) => record.packId === packId).map((record) => record.item)
  },
  async removeQueued(packId: string, ids: string[]) {
    const db = await openDb()
    await new Promise<void>((resolve, reject) => {
      const transaction = db.transaction(QUEUE_STORE, 'readwrite')
      const store = transaction.objectStore(QUEUE_STORE)
      ids.forEach((id) => store.delete(`${packId}:${id}`))
      transaction.oncomplete = () => { db.close(); resolve() }
      transaction.onerror = () => { db.close(); reject(transaction.error) }
    })
  },
  async clearPack(deviceSessionId: string, packId: string) {
    await tx<undefined>(PACK_STORE, 'readwrite', (store) => store.delete(deviceSessionId))
    const items = await this.queued(packId)
    await this.removeQueued(packId, items.map((item) => item.client_scan_id))
  },
  async saveDeviceSession(session: StoredFieldSession, userId: string) {
    await putEncrypted(SESSION_STORE, session.tenantId, { session, userId } satisfies StoredSession)
  },
  async getDeviceSession(tenantId: string) {
    return getEncrypted<StoredSession>(SESSION_STORE, tenantId)
  },
  async clearDeviceSession(tenantId: string) {
    await tx<undefined>(SESSION_STORE, 'readwrite', (store) => store.delete(tenantId))
  },
}
