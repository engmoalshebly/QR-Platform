import {
  Settings2,
  ChevronUp,
  ChevronDown,
  Grid3X3,
  Eye,
  EyeOff,
} from 'lucide-react'
import { GRID_PRESETS, BARCODE_SIZES } from './types'

interface LayoutSettingsProps {
  showSettings: boolean
  setShowSettings: (val: boolean) => void
  layout: {
    rows: number
    cols: number
    barcode_size_px: number | null
    page_size: 'A4' | 'Letter'
    orientation: 'portrait' | 'landscape'
    show_guest_name: boolean
    show_code_text: boolean
  }
  updateLayout: (updates: Partial<LayoutSettingsProps['layout']>) => void
  totalInvitations: number
  estimatedPages: number
  barcodePerPage: number
}

export function LayoutSettings({
  showSettings,
  setShowSettings,
  layout,
  updateLayout,
  totalInvitations,
  estimatedPages,
  barcodePerPage,
}: LayoutSettingsProps) {
  return (
    <div className="inv-settings-panel">
      <button className="inv-settings-toggle" onClick={() => setShowSettings(!showSettings)}>
        <div className="inv-settings-toggle__right">
          <Settings2 size={16} style={{ color: 'var(--color-primary)' }} />
          <span>إعدادات الطباعة وتوزيع الدعوات</span>
          {totalInvitations > 0 && (
            <span className="inv-settings-tag">
              {layout.rows}×{layout.cols} · {estimatedPages} صفحة
            </span>
          )}
        </div>
        {showSettings ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
      </button>

      {showSettings && (
        <div className="inv-settings-body">
          {/* Grid Presets */}
          <div>
            <label className="inv-label" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <Grid3X3 size={14} style={{ opacity: 0.7 }} /> حجم الشبكة (صفوف × أعمدة)
            </label>
            <div className="inv-chip-group">
              {GRID_PRESETS.map((p) => (
                <button
                  key={p.label}
                  className={`inv-chip ${layout.rows === p.rows && layout.cols === p.cols ? 'inv-chip--active' : ''}`}
                  onClick={() => updateLayout({ rows: p.rows, cols: p.cols })}
                >
                  {p.label}
                </button>
              ))}
            </div>
            <div className="inv-custom-grid">
              <div className="inv-custom-grid__field">
                <span>صفوف</span>
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={layout.rows}
                  onChange={(e) =>
                    updateLayout({ rows: Math.max(1, Math.min(20, parseInt(e.target.value) || 1)) })
                  }
                  className="inv-input inv-input--sm"
                />
              </div>
              <span className="inv-custom-grid__sep">×</span>
              <div className="inv-custom-grid__field">
                <span>أعمدة</span>
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={layout.cols}
                  onChange={(e) =>
                    updateLayout({ cols: Math.max(1, Math.min(20, parseInt(e.target.value) || 1)) })
                  }
                  className="inv-input inv-input--sm"
                />
              </div>
              <span className="inv-custom-grid__info">= {barcodePerPage} دعوات/صفحة</span>
            </div>
          </div>

          {/* Barcode Size */}
          <div>
            <label className="inv-label">حجم صورة رمز QR (بكسل)</label>
            <div className="inv-chip-group">
              {BARCODE_SIZES.map((s) => (
                <button
                  key={s.label}
                  className={`inv-chip ${layout.barcode_size_px === s.value ? 'inv-chip--active' : ''}`}
                  onClick={() => updateLayout({ barcode_size_px: s.value })}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>

          {/* Page size & orientation */}
          <div className="inv-grid-2">
            <div>
              <label className="inv-label">حجم الصفحة</label>
              <select
                value={layout.page_size}
                onChange={(e) => updateLayout({ page_size: e.target.value as 'A4' | 'Letter' })}
                className="inv-input"
              >
                <option value="A4">A4</option>
                <option value="Letter">Letter</option>
              </select>
            </div>
            <div>
              <label className="inv-label">الاتجاه</label>
              <select
                value={layout.orientation}
                onChange={(e) => updateLayout({ orientation: e.target.value as 'portrait' | 'landscape' })}
                className="inv-input"
              >
                <option value="portrait">عمودي (Portrait)</option>
                <option value="landscape">أفقي (Landscape)</option>
              </select>
            </div>
          </div>

          {/* Toggles */}
          <div className="inv-toggle-row">
            <button
              className={`inv-toggle-btn ${layout.show_guest_name ? 'inv-toggle-btn--on' : ''}`}
              onClick={() => updateLayout({ show_guest_name: !layout.show_guest_name })}
            >
              {layout.show_guest_name ? <Eye size={14} /> : <EyeOff size={14} />} اسم الضيف
            </button>
            <button
              className={`inv-toggle-btn ${layout.show_code_text ? 'inv-toggle-btn--on' : ''}`}
              onClick={() => updateLayout({ show_code_text: !layout.show_code_text })}
            >
              {layout.show_code_text ? <Eye size={14} /> : <EyeOff size={14} />} رمز الدعوة
            </button>
          </div>

          {/* Summary */}
          {totalInvitations > 0 && (
            <div className="inv-summary-bar">
              <span>
                <strong>{totalInvitations}</strong> دعوة
              </span>
              <span className="inv-summary-bar__dot" />
              <span>
                <strong>
                  {layout.rows}×{layout.cols}
                </strong>{' '}
                شبكة
              </span>
              <span className="inv-summary-bar__dot" />
              <span>
                <strong>{estimatedPages}</strong> صفحة
              </span>
              <span className="inv-summary-bar__dot" />
              <span>
                رمز QR:{' '}
                <strong>
                  {layout.barcode_size_px ? `${layout.barcode_size_px}px` : 'تلقائي'}
                </strong>
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
