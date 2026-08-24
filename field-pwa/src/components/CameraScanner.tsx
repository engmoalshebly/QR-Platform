import { BrowserMultiFormatReader, IScannerControls } from '@zxing/browser'
import { BarcodeFormat, DecodeHintType, NotFoundException } from '@zxing/library'
import { useEffect, useRef, useState } from 'react'

export function CameraScanner({ active, onCode, onError }: { active: boolean; onCode: (code: string, method: 'camera' | 'code128') => void; onError: (message: string) => void }) {
  const video = useRef<HTMLVideoElement>(null)
  const controls = useRef<IScannerControls | null>(null)
  const locked = useRef(false)
  const [state, setState] = useState<'idle' | 'starting' | 'ready' | 'error'>('idle')

  useEffect(() => {
    if (!active || !video.current) return
    const hints = new Map<DecodeHintType, BarcodeFormat[]>()
    hints.set(DecodeHintType.POSSIBLE_FORMATS, [BarcodeFormat.QR_CODE, BarcodeFormat.CODE_128])
    const reader = new BrowserMultiFormatReader(hints, { delayBetweenScanAttempts: 200, delayBetweenScanSuccess: 900 })
    let disposed = false
    setState('starting')
    void reader.decodeFromConstraints(
      { video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false },
      video.current,
      (result, error) => {
        if (disposed) return
        if (result && !locked.current) {
          locked.current = true
          navigator.vibrate?.(35)
          onCode(result.getText(), result.getBarcodeFormat() === BarcodeFormat.CODE_128 ? 'code128' : 'camera')
          window.setTimeout(() => { locked.current = false }, 1100)
        } else if (error && !(error instanceof NotFoundException)) {
          setState('error')
          onError('تعذر قراءة الكاميرا. استخدم الإدخال اليدوي أو أعد فتح الكاميرا.')
        }
      },
    ).then((nextControls) => {
      if (disposed) nextControls.stop()
      else { controls.current = nextControls; setState('ready') }
    }).catch(() => {
      if (!disposed) { setState('error'); onError('لم يتم السماح بالكاميرا. تحقق من الإذن ثم حاول مجدداً.') }
    })
    return () => { disposed = true; controls.current?.stop(); controls.current = null }
  }, [active, onCode, onError])

  return <div className="camera-shell"><video ref={video} className="camera-view" muted playsInline /><div className="camera-frame" aria-hidden="true" /><p className="camera-status">{state === 'starting' ? 'جارٍ تشغيل الكاميرا…' : state === 'ready' ? 'وجّه الرمز داخل الإطار' : state === 'error' ? 'تعذر فتح الكاميرا' : 'الكاميرا متوقفة'}</p></div>
}
