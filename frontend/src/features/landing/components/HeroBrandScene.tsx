import { ArrowUpLeft } from 'lucide-react'

export function HeroBrandScene() {
  return <figure className="hero-photo"><div className="hero-photo__frame"><img src="/brand/editorial/dawaa-arrival.webp" alt="استقبال أنيق للضيوف مع دعوة رقمية على الهاتف" width="960" height="1200" fetchPriority="high"/><div className="hero-photo__shade"/><figcaption><span>كل وصول يبدأ بدعوة</span><strong>تفاصيل شخصية.<br/>لحظة استقبال مميزة.</strong><ArrowUpLeft size={25}/></figcaption></div><span className="hero-photo__note">صورة توضيحية لتجربة الاستقبال</span></figure>
}
