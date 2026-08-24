import { useEffect, useState, type CSSProperties } from 'react'
import QRCode from 'qrcode'

type LocalQrCodeProps = {
  value: string
  size?: number
  alt: string
  className?: string
  style?: CSSProperties
}

/** Generate QR pixels in the browser so invitation credentials never leave it. */
export async function createLocalQrDataUrl(value: string, size = 250): Promise<string> {
  return QRCode.toDataURL(value, {
    errorCorrectionLevel: 'M',
    margin: 1,
    width: size,
    color: {
      dark: '#000000',
      light: '#FFFFFF',
    },
  })
}

/**
 * A local replacement for remote QR-image services.  The encoded invitation
 * token stays inside the browser rather than becoming a third-party request
 * URL.
 */
export function LocalQrCode({ value, size = 250, alt, className, style }: LocalQrCodeProps) {
  const [src, setSrc] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    setSrc(null)
    void createLocalQrDataUrl(value, size)
      .then((dataUrl) => {
        if (active) setSrc(dataUrl)
      })
      .catch(() => {
        if (active) setSrc(null)
      })
    return () => {
      active = false
    }
  }, [size, value])

  if (!src) {
    return <span className={className} style={style} role="img" aria-label={alt} aria-busy="true" />
  }

  return <img src={src} alt={alt} className={className} style={style} />
}
