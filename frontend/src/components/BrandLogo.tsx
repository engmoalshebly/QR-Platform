import { useId } from 'react'
import { useAdminTheme } from '@app/theme/ThemeProvider'
import './brand-logo.css'

type BrandLogoProps = {
  className?: string
  symbol?: boolean
}

/** Uses the reviewed original artwork; viewBox removes display whitespace only. */
export function BrandLogo({ className = '', symbol = false }: BrandLogoProps) {
  const { theme } = useAdminTheme()
  const filterId = `dawaa-${useId().replace(/:/g, '')}`
  if (symbol) {
    return <img className={`dawaa-symbol ${className}`} src="/brand/dawaa-app-icon-ivory.png" alt="دعوة — DAWAA" />
  }

  return (
    <svg className={`dawaa-logo ${className}`} viewBox="175 275 1140 660" role="img" aria-label="دعوة — DAWAA، من الدعوة إلى الدخول">
      <defs>
        <filter id={filterId} colorInterpolationFilters="sRGB">
          {/* Navy becomes ivory while the gold details retain their warm color. */}
          <feColorMatrix type="matrix" values="-0.225 0 0 0 0.98  -0.4625 0 0 0 0.97  -0.975 0 0 0 0.93  0 0 0 1 0" />
        </filter>
      </defs>
      <image filter={theme === 'dark' ? `url(#${filterId})` : undefined} href="/brand/dawaa-logo-navy-gold-tagline-transparent.png" width="1448" height="1086" />
    </svg>
  )
}
