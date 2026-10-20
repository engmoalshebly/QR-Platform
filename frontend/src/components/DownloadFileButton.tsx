import { useState, type ReactNode } from 'react'
import { downloadAuthenticatedFile, getApiErrorMessage } from '@services/http/client'

type Props = { url: string; filename: string; className?: string; children: ReactNode }

export function DownloadFileButton({ url, filename, className, children }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const download = async () => {
    if (busy) return
    setBusy(true)
    setError(null)
    try { await downloadAuthenticatedFile(url, filename) }
    catch (cause) { setError(getApiErrorMessage(cause, 'تعذر تنزيل الملف. أعد المحاولة.')) }
    finally { setBusy(false) }
  }
  return <span>
    <button type="button" className={className} disabled={busy} aria-busy={busy} onClick={download}>
      {busy ? 'جار التنزيل…' : children}
    </button>
    {error && <span role="alert" style={{ display: 'block', color: 'var(--color-danger)', fontSize: 12 }}>{error}</span>}
  </span>
}
