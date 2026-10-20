import { useEffect, useState } from 'react'
import { CalendarDays, ShieldCheck, Sparkles } from 'lucide-react'
import { BrandLogo } from '@components/BrandLogo'

const showcaseSlides = [
  {
    image: '/auth-showcase/heritage-event.png',
    eyebrow: 'فعاليات تُدار بثقة',
    title: 'تفاصيل دقيقة لتجربة ضيف استثنائية',
    description: 'من الدعوة الأولى حتى تأكيد الحضور عند البوابة، كل شيء في مكان واحد.',
    Icon: Sparkles,
  },
  {
    image: '/auth-showcase/celebration-hall.png',
    eyebrow: 'تنظيم بمستوى راقٍ',
    title: 'كل مناسبة تبدأ بخطة واضحة',
    description: 'أنشئ حفلك، وزّع المهام، وتابع تقدّم الفريق من لوحة تشغيل موحدة.',
    Icon: CalendarDays,
  },
  {
    image: '/auth-showcase/conference-stage.png',
    eyebrow: 'تشغيل ميداني متصل',
    title: 'حضور أسرع وبيانات أدق',
    description: 'إدارة الدعوات والبوابات والحضور المباشر بتجربة احترافية وآمنة.',
    Icon: ShieldCheck,
  },
] as const

export function AuthShowcase() {
  const [activeSlide, setActiveSlide] = useState(0)
  const active = showcaseSlides[activeSlide]

  useEffect(() => {
    const timer = window.setInterval(() => {
      setActiveSlide((current) => (current + 1) % showcaseSlides.length)
    }, 6500)
    return () => window.clearInterval(timer)
  }, [])

  const Icon = active.Icon

  return (
    <aside className="auth-showcase" aria-label="لمحة عن منصة دعوة">
      <div className="auth-showcase__scenes" aria-hidden="true">
        {showcaseSlides.map((slide, index) => (
          <div
            className={`auth-showcase__scene${index === activeSlide ? ' is-active' : ''}`}
            key={slide.image}
            style={{ backgroundImage: `url(${slide.image})` }}
          />
        ))}
      </div>
      <div className="auth-showcase__veil" aria-hidden="true" />

      <div className="auth-showcase__brand">
        <BrandLogo symbol />
        <span>دعوة | من الدعوة إلى الدخول</span>
      </div>

      <div className="auth-showcase__copy" key={active.image}>
        <span className="auth-showcase__eyebrow"><Icon size={17} /> {active.eyebrow}</span>
        <h2>{active.title}</h2>
        <p>{active.description}</p>
      </div>

      <div className="auth-showcase__footer">
        <div className="auth-showcase__dots" aria-label="شرائح تعريفية">
          {showcaseSlides.map((slide, index) => (
            <button
              aria-label={`عرض الشريحة ${index + 1}`}
              aria-pressed={index === activeSlide}
              className={index === activeSlide ? 'is-active' : ''}
              key={slide.image}
              onClick={() => setActiveSlide(index)}
              type="button"
            />
          ))}
        </div>
        <span>منصة تشغيل الفعاليات</span>
      </div>
    </aside>
  )
}
