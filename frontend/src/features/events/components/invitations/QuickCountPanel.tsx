import { Sparkles, Users } from 'lucide-react'

interface QuickCountPanelProps {
  remainingVip: number
  remainingNormal: number
  vipCount: number
  setVipCount: (val: number) => void
  normalCount: number
  setNormalCount: (val: number) => void
  guestPrefix: string
  setGuestPrefix: (val: string) => void
  isPending: boolean
}

export function QuickCountPanel({
  remainingVip,
  remainingNormal,
  vipCount,
  setVipCount,
  normalCount,
  setNormalCount,
  guestPrefix,
  setGuestPrefix,
  isPending,
}: QuickCountPanelProps) {
  return (
    <>
      <div className="inv-grid-2">
        {/* VIP */}
        <div className="inv-tier-box inv-tier-box--vip">
          <div className="inv-tier-box__glow" />
          <div className="inv-tier-box__head">
            <span className="inv-tier-box__label inv-tier-box__label--vip">
              <Sparkles size={15} /> تذاكر VIP
            </span>
            <span className="inv-tier-box__badge inv-tier-box__badge--vip">المتبقي: {Number.isFinite(remainingVip) ? remainingVip : 'غير محدود'}</span>
          </div>
          <label className="inv-label">عدد الدعوات المطلوب توليدها</label>
          <input
            type="number"
            min={0}
            max={Number.isFinite(remainingVip) ? remainingVip : 'غير محدود'}
            value={vipCount || ''}
            onChange={(e) => setVipCount(Math.max(0, Math.min(1000, Number(e.target.value) || 0)))}
            className="inv-input"
            placeholder="0"
            disabled={isPending}
          />
        </div>

        {/* Normal */}
        <div className="inv-tier-box inv-tier-box--normal">
          <div className="inv-tier-box__head">
            <span className="inv-tier-box__label">
              <Users size={15} /> تذاكر الدخول العادي
            </span>
            <span className="inv-tier-box__badge">المتبقي: {Number.isFinite(remainingNormal) ? remainingNormal : 'غير محدود'}</span>
          </div>
          <label className="inv-label">عدد الدعوات المطلوب توليدها</label>
          <input
            type="number"
            min={0}
            max={Number.isFinite(remainingNormal) ? remainingNormal : 'غير محدود'}
            value={normalCount || ''}
            onChange={(e) => setNormalCount(Math.max(0, Math.min(1000, Number(e.target.value) || 0)))}
            className="inv-input"
            placeholder="0"
            disabled={isPending}
          />
        </div>
      </div>

      {/* Guest prefix */}
      <div style={{ maxWidth: 400, marginBottom: 8 }}>
        <label className="inv-label">بادئة اسم الضيف (مثال: ضيف 1، ضيف 2)</label>
        <input
          type="text"
          value={guestPrefix}
          onChange={(e) => setGuestPrefix(e.target.value)}
          className="inv-input"
          placeholder="ضيف"
          disabled={isPending}
        />
      </div>
    </>
  )
}
