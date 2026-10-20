import { HeroBrandScene } from '../components/HeroBrandScene'
import { BrandLogo } from '@components/BrandLogo'
import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { AnimatePresence, motion, useReducedMotion, useScroll, useSpring } from 'framer-motion'
import { ArrowLeft, ArrowUpLeft, CalendarPlus, Presentation, LayoutGrid, GraduationCap, Building2, Sparkles, Check, CheckCircle2, ChevronDown, Clock3, Mail, Menu, Moon, ShieldCheck, Signal, Sun, Users, WifiOff, X } from 'lucide-react'
import { subscriptionsAPI, type Plan } from '@features/settings/api/subscriptionsApi'
import { LocalQrCode } from '@shared/components/LocalQrCode'
import { useAdminTheme } from '@app/theme/ThemeProvider'
import { formatUsd, formatYer } from '@shared/utils/currency'
import './landing.css'
import './hero-brand.css'

const journey = ['إنشاء الفعالية', 'إرسال الدعوة', 'تأكيد الحضور', 'الوصول', 'التحقق', 'الدخول', 'المتابعة']
const useCases = [
  { icon: Presentation, label: 'لقاءات تصنع الأثر', tags: ['دعوات شخصية', 'تأكيد الحضور', 'دخول منظّم'], title: 'المؤتمرات', copy: 'دعوات شخصية، تأكيدات حضور، وتنظيم دخول المشاركين.' },
  { icon: LayoutGrid, label: 'مساحات للقاء والاكتشاف', tags: ['البوابات', 'فريق الاستقبال'], title: 'المعارض', copy: 'بوابات محددة وورديات واضحة لفريق الاستقبال.' },
  { icon: GraduationCap, label: 'لحظات تستحق الاحتفاء', tags: ['تفاصيل الحفل', 'المرافقون'], title: 'حفلات التخرج', copy: 'دعوة واحدة تجمع تفاصيل الحفل وعدد المرافقين المسموح.' },
  { icon: Building2, label: 'حضور يعكس هويتك', tags: ['هوية الشركة', 'ردود المدعوين'], title: 'فعاليات الشركات', copy: 'تصميم يعكس هوية الشركة، مع متابعة ردود المدعوين.' },
  { icon: Sparkles, label: 'تفاصيل أقرب إلى ضيوفك', tags: ['دعوة شخصية', 'تجربة الضيف'], title: 'المناسبات الخاصة', copy: 'تجربة شخصية للضيوف، من فتح الدعوة إلى الوصول.' },
]
const gettingStarted = [
  { title: 'جهّز تفاصيل مناسبتك', copy: 'حدّد الموعد والمكان، ثم اختر تصميمًا يعكس هوية المناسبة.' },
  { title: 'خصّص دعوات ضيوفك', copy: 'أضف المدعوين وبياناتهم، وجهّز الدعوات وتابع تأكيدات الحضور.' },
  { title: 'رتّب استقبالهم', copy: 'اضبط البوابات وقواعد الدخول، وأسند الفريق إلى الورديات قبل بدء الاستقبال.' },
]
const comparison = [
  ['الدعوات', 'إرسال ومتابعة من مكان واحد', 'ملفات ورسائل منفصلة'],
  ['الدخول', 'تحقق مباشر من حالة الضيف', 'قوائم ورقية أو بحث يدوي'],
  ['الأجهزة', 'هواتف فريق التنظيم', 'قد تتطلب تجهيزات إضافية'],
  ['الاتصال', 'حزمة عمل دون اتصال في نسخة الويب الميدانية', 'تحتاج خطة بديلة عند ضعف الشبكة'],
  ['التكرار', 'التحقق من السعة وقواعد إعادة الدخول', 'يصعب اكتشافه لحظيًا'],
  ['المتابعة', 'ملخص الحضور وسجل الدخول', 'اتصالات وتحديثات متفرقة'],
]
const faqs = [
  { q: 'هل يحتاج الضيف إلى تطبيق؟', a: 'لا. يفتح الضيف رابط الدعوة من هاتفه ويستطيع مراجعة التفاصيل وتأكيد الحضور وعرض رمز الدخول من المتصفح.' },
  { q: 'كيف تتعامل دعوة مع تكرار المسح؟', a: 'يتحقق النظام من صلاحية الدعوة وعدد الأشخاص المتبقي عند المسح المتصل. عند استهلاك العدد المسموح، يرفض الدخول الإضافي ما لم تسمح إعدادات الفعالية بإعادة الدخول.' },
  { q: 'هل تعمل البوابات عند ضعف الاتصال؟', a: 'تدعم نسخة الويب الميدانية العمل دون اتصال بعد تنزيل حزمة الوردية مسبقًا. القبول المحلي مؤقت، وتُراجع النتائج عند المزامنة؛ قد تظهر تعارضات إذا استُخدمت الدعوة على أكثر من جهاز. تطبيق الجوال يحتاج الاتصال للمسح حاليًا.' },
  { q: 'هل يمكن تصميم الدعوات والبطاقات داخل المنصة؟', a: 'نعم. يتيح محرر التصميم إضافة عناصر ثابتة ومتغيرات الضيف ورمز QR إلى الدعوات والبطاقات.' },
  { q: 'هل يمكن إدارة عدة بوابات وفرق؟', a: 'نعم. يمكنك إنشاء البوابات وتوزيع المناوبات والمسؤوليات ومتابعة حالة الدخول من لوحة العمليات.' },
]

function Reveal({ children, className = '', delay = 0 }: { children: ReactNode; className?: string; delay?: number }) {
  const reduced = useReducedMotion()
  return <motion.div className={`landing-reveal ${className}`} initial={reduced ? false : { opacity: 0, y: 18 }} whileInView={reduced ? undefined : { opacity: 1, y: 0 }} viewport={{ once: true, amount: .15 }} transition={{ duration: .55, delay, ease: [0.16, 1, 0.3, 1] }}>{children}</motion.div>
}

function SectionTitle({ eyebrow, title, copy }: { eyebrow: string; title: string; copy?: string }) {
  return <div className="landing-section-title"><span>{eyebrow}</span><h2>{title}</h2>{copy && <p>{copy}</p>}</div>
}

function InvitationPreview() {
  return <div className="guest-invitation-scene" aria-label="معاينة توضيحية لدعوة شخصية">
    <article className="guest-invitation">
      <header className="guest-invitation-cover"><span className="guest-invitation-brand">DAWAA <i/> دعوة</span><span className="guest-invitation-eyebrow">يسرّنا دعوتكم إلى</span><h3>ملتقى<br/>الابتكار</h3><p>أفكار تلتقي. وآفاق تتّسع.</p><span className="guest-invitation-edition">INVITATION · 2026</span></header>
      <div className="guest-invitation-body"><div className="guest-invitation-person"><small>دعوة خاصة إلى</small><strong>ضيفنا الكريم</strong><span>نتطلع إلى حضوركم ومشاركتكم</span></div>
        <div className="guest-invitation-details"><div><Clock3 size={16}/><span><small>الموعد</small><strong>الخميس، 24 سبتمبر</strong><em>7:30 مساءً</em></span></div><div><Users size={16}/><span><small>المكان</small><strong>قاعة الملتقى · الرياض</strong><em>البوابة الرئيسية</em></span></div></div>
        <div className="guest-invitation-ticket"><div className="guest-invitation-qr"><LocalQrCode value="DAWAA-GUEST-DEMO" size={82} alt="رمز دعوة توضيحي"/></div><div><span className="guest-invitation-vip">VIP</span><strong>رمز وصولك الخاص</strong><p>أبرز الدعوة لفريق الاستقبال عند الوصول.</p><small>ضيف واحد · مقعد A12</small></div></div>
        <div className="guest-invitation-rsvp"><CheckCircle2 size={17}/><span>تم تأكيد الحضور</span><span><CalendarPlus size={14}/> الموعد في التقويم</span></div>
      </div>
    </article><p className="guest-invitation-note">دعوة وبيانات توضيحية لتجربة الضيف</p>
  </div>
}

function ScannerPreview() {
  return <div className="scanner-device-scene">
    <div className="scanner-device" aria-label="نموذج هاتف يعرض تجربة مسح رمز الدخول">
      <i className="scanner-device-button scanner-device-button--volume" aria-hidden="true"/><i className="scanner-device-button scanner-device-button--power" aria-hidden="true"/>
      <div className="scanner-device-screen">
        <div className="scanner-statusbar"><span>9:41</span><div className="scanner-island"/><div><Signal size={13}/><span className="scanner-battery"/></div></div>
        <div className="scanner-app-header"><BrandLogo symbol/><span>دعوة · المسح الميداني</span></div>
        <div className="scanner-shell">
          <div className="scanner-top"><span>البوابة الرئيسية</span><strong><span/> متصل</strong></div>
          <div className="scanner-camera"><div className="scanner-corners"/><div className="scanner-line"/><div className="scanner-code"><LocalQrCode value="QENTRY-SCAN-DEMO" size={100} alt="رمز دخول توضيحي"/></div><span className="scanner-camera-hint">ضع رمز الدعوة داخل الإطار</span></div>
          <div className="scanner-result"><span><Check size={22}/></span><div><small>تم التحقق من الدعوة</small><strong>ضيف تجريبي</strong><p>VIP · ضيف واحد</p></div><em>سماح بالدخول</em></div>
          <div className="scanner-duplicate"><ShieldCheck size={16}/><span>التحقق وفق سعة الدعوة وقواعد الدخول</span></div>
          <div className="scanner-app-actions"><span>بحث عن دعوة</span><span>طلب مساعدة</span></div>
        </div>
        <div className="scanner-home-indicator"/>
      </div>
    </div>
    <p className="scanner-device-note">معاينة توضيحية لتجربة فريق الاستقبال</p>
  </div>
}

function CommandCenterPreview() {
  return <div className="attendance-preview" aria-label="لوحة توضيحية لمتابعة الحضور">
    <div className="attendance-toolbar"><div className="attendance-window" aria-hidden="true"><i/><i/><i/></div><span>دعوة / متابعة الحضور</span><small>معاينة ببيانات توضيحية</small></div>
    <div className="attendance-body">
      <header className="attendance-header"><div><span>ملتقى الابتكار</span><h3>نظرة على الاستقبال</h3></div><span className="attendance-date"><Clock3 size={14}/> الخميس · 24 سبتمبر</span></header>
      <div className="attendance-metrics">{[['حركات الدخول','248','شخص تم تسجيل دخوله'],['دعوات متبقية','132','لم تستنفد سعتها'],['الفريق المكلّف','12','عضو عبر 4 بوابات']].map(([label,value,note],i)=><div key={label}><span>{label}{i===0?<Users size={17}/>:i===1?<CalendarPlus size={17}/>:<ShieldCheck size={17}/>}</span><strong>{value}</strong><small>{note}</small></div>)}</div>
      <div className="attendance-panels">
        <div className="attendance-chart"><div className="attendance-panel-heading"><div><h4>حركة الوصول</h4><p>حركات الدخول المسجّلة خلال المساء</p></div><span><i/> الدخول</span></div><div className="attendance-plot"><div className="attendance-y"><span>80</span><span>60</span><span>40</span><span>20</span><span>0</span></div><svg viewBox="0 0 600 190" role="img" aria-label="حركات دخول توضيحية عبر خمس فترات زمنية"><defs><linearGradient id="attendanceFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#D4A32C" stopOpacity=".25"/><stop offset="1" stopColor="#D4A32C" stopOpacity="0"/></linearGradient></defs>{[10,50,90,130,170].map(y=><line key={y} x1="0" x2="600" y1={y} y2={y} stroke="currentColor" strokeDasharray="4 6"/>)}<path d="M0 158 C55 158 75 136 120 136 S195 88 250 94 S310 61 370 65 S470 18 510 36 S570 35 600 25 L600 190 L0 190Z" fill="url(#attendanceFill)"/><path d="M0 158 C55 158 75 136 120 136 S195 88 250 94 S310 61 370 65 S470 18 510 36 S570 35 600 25" fill="none" stroke="#D4A32C" strokeWidth="3"/><circle cx="600" cy="25" r="5" fill="#D4A32C"/></svg></div><div className="attendance-x"><span>18:00</span><span>18:30</span><span>19:00</span><span>19:30</span><span>20:00</span></div></div>
        <aside className="attendance-gates"><div className="attendance-panel-heading"><h4>توزيع الدخول</h4><span>4 بوابات</span></div>{['البوابة الرئيسية','بوابة VIP','البوابة الشرقية','مدخل الفريق'].map((gate,i)=><div className="attendance-gate" key={gate}><div><span>{gate}</span><strong>{[104,72,54,18][i]}</strong></div><div className="attendance-gate-track"><i style={{width:`${[100,69,52,17][i]}%`}}/></div></div>)}</aside>
      </div>
      <div className="attendance-recent"><div className="attendance-panel-heading"><h4>آخر عمليات الدخول</h4><span>سجل توضيحي</span></div><div className="attendance-table"><div><span>الفئة</span><span>البوابة</span><span>العدد</span><span>الوقت</span><span>القرار</span></div>{[['VIP','بوابة VIP','1','19:42'],['عادية','البوابة الرئيسية','2','19:41']].map(row=><div key={row[3]}>{row.map((cell,i)=><span key={i}>{cell}</span>)}<span className="attendance-accepted"><Check size={12}/> مقبول</span></div>)}</div></div>
    </div>
  </div>
}

function DesignStudioPreview() {
  return <figure className="editorial-photo"><img src="/brand/editorial/dawaa-design.webp" alt="مساحة تصميم دعوات متناسقة على الحاسوب والهاتف" width="1200" height="800" loading="lazy" decoding="async"/><figcaption>هوية واحدة، بتفاصيل تخص كل ضيف.</figcaption></figure>
}

export default function LandingPage() {
  const { theme, toggleTheme } = useAdminTheme()
  const [scrolled,setScrolled]=useState(false), [menuOpen,setMenuOpen]=useState(false), [openFaq,setOpenFaq]=useState<number|null>(0), [plans,setPlans]=useState<Plan[]>([])
  const [activeSection,setActiveSection]=useState('home')
  const { scrollYProgress } = useScroll()
  const progress = useSpring(scrollYProgress,{stiffness:150,damping:28,mass:.25})
  useEffect(()=>{const handle=()=>setScrolled(window.scrollY>24);window.addEventListener('scroll',handle,{passive:true});document.title='دعوة | DAWAA — من الدعوة إلى الدخول';return()=>window.removeEventListener('scroll',handle)},[])
  useEffect(()=>{let mounted=true;subscriptionsAPI.listPlans().then(items=>{if(mounted)setPlans(items.filter(p=>p.is_active).sort((a,b)=>a.sort_order-b.sort_order))}).catch(()=>undefined);return()=>{mounted=false}},[])
  useEffect(()=>{
    const sections=Array.from(document.querySelectorAll<HTMLElement>('.landing>section, .landing-footer'))
    const observer=new IntersectionObserver(entries=>{
      entries.forEach(entry=>{if(entry.isIntersecting){entry.target.classList.add('section-visible');observer.unobserve(entry.target)}})
    },{threshold:0,rootMargin:'0px 0px -60px 0px'})
    sections.forEach(section=>observer.observe(section))
    return()=>observer.disconnect()
  },[])
  useEffect(()=>{
    const root=document.querySelector<HTMLElement>('.landing')
    if(!root)return
    const sections=Array.from(root.querySelectorAll<HTMLElement>('section[id]'))
    const reduced=window.matchMedia('(prefers-reduced-motion: reduce)')
    let frame=0, trackingFrame=0
    const cancel=()=>{cancelAnimationFrame(frame);frame=0;root.classList.remove('is-navigating')}
    const track=()=>{
      trackingFrame=0
      const passed=sections.filter(section=>section.getBoundingClientRect().top<=160)
      const current=passed[passed.length-1]
      const groups:Record<string,string>={home:'platform',attendance:'gates',occasions:'platform',difference:'platform','getting-started':'platform',faq:'pricing'}
      const sectionId=current?.id??'home'
      setActiveSection(groups[sectionId]??sectionId)
    }
    const onScroll=()=>{if(!trackingFrame)trackingFrame=requestAnimationFrame(track)}
    const onKey=(event:KeyboardEvent)=>{if(['ArrowDown','ArrowUp','PageDown','PageUp','Home','End','Escape',' '].includes(event.key))cancel()}
    const navigate=(event:MouseEvent)=>{
      if(event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return
      const anchor=(event.target as Element).closest<HTMLAnchorElement>('a[href^="#"]')
      const target=anchor?.hash?document.getElementById(anchor.hash.slice(1)):null
      if(!anchor||!target||!root.contains(target))return
      event.preventDefault();cancel();setMenuOpen(false)
      const start=window.scrollY
      const offset=(root.querySelector('header')?.getBoundingClientRect().height??80)+20
      const destination=Math.max(0,Math.min(start+target.getBoundingClientRect().top-offset,document.documentElement.scrollHeight-window.innerHeight))
      const distance=destination-start
      const duration=Math.min(1400,Math.max(650,Math.abs(distance)*.12))
      const started=performance.now()
      const finish=()=>{
        root.classList.remove('is-navigating')
        history.replaceState(history.state,'',anchor.hash)
        target.classList.remove('navigation-arrived')
        void target.offsetWidth
        target.classList.add('navigation-arrived')
        track()
      }
      if(reduced.matches){window.scrollTo({top:destination,behavior:'instant'});finish();return}
      root.classList.add('is-navigating')
      const step=(now:number)=>{
        const t=Math.min(1,(now-started)/duration)
        const eased=t<.5?4*t*t*t:1-Math.pow(-2*t+2,3)/2
        window.scrollTo({top:start+distance*eased,behavior:'instant'})
        if(t<1)frame=requestAnimationFrame(step)
        else{frame=0;finish()}
      }
      frame=requestAnimationFrame(step)
    }
    root.addEventListener('click',navigate)
    window.addEventListener('scroll',onScroll,{passive:true})
    window.addEventListener('wheel',cancel,{passive:true})
    window.addEventListener('touchstart',cancel,{passive:true})
    window.addEventListener('keydown',onKey)
    track()
    return()=>{
      cancel();cancelAnimationFrame(trackingFrame)
      root.removeEventListener('click',navigate)
      window.removeEventListener('scroll',onScroll)
      window.removeEventListener('wheel',cancel)
      window.removeEventListener('touchstart',cancel)
      window.removeEventListener('keydown',onKey)
    }
  },[])
  const closeMenu=()=>setMenuOpen(false)
  return <main className="landing" dir="rtl">
    <motion.div className="scroll-progress" style={{scaleX:progress}} aria-hidden="true"/>
    <header className={`landing-header ${scrolled?'is-scrolled':''}`}><nav className="landing-nav" aria-label="التنقل الرئيسي"><a href="#home" className="landing-logo" aria-label="دعوة الرئيسية"><BrandLogo /></a><div id="landing-menu" className={`landing-links ${menuOpen?'is-open':''}`}><a href="#platform" onClick={closeMenu} aria-current={activeSection==='platform'?'location':undefined}>المنظومة</a><a href="#invitations" onClick={closeMenu} aria-current={activeSection==='invitations'?'location':undefined}>الدعوات</a><a href="#gates" onClick={closeMenu} aria-current={activeSection==='gates'?'location':undefined}>البوابات</a><a href="#operations" onClick={closeMenu} aria-current={activeSection==='operations'?'location':undefined}>التشغيل الميداني</a><a href="#pricing" onClick={closeMenu} aria-current={activeSection==='pricing'?'location':undefined}>الأسعار</a></div><div className="landing-actions"><button type="button" className="theme-toggle" onClick={toggleTheme} title={theme==='dark'?'تفعيل الوضع الفاتح':'تفعيل الوضع الداكن'} aria-label={theme==='dark'?'تفعيل الوضع الفاتح':'تفعيل الوضع الداكن'}>{theme==='dark'?<Sun size={17}/>:<Moon size={17}/>}</button><Link to="/auth/login" className="login-link">تسجيل الدخول</Link><Link to="/auth/signup" className="primary-button">ابدأ مجانًا <ArrowUpLeft size={17}/></Link></div><button className="menu-button" type="button" onClick={()=>setMenuOpen(v=>!v)} aria-expanded={menuOpen} aria-controls="landing-menu" aria-label={menuOpen?'إغلاق القائمة':'فتح القائمة'}>{menuOpen?<X/>:<Menu/>}</button></nav></header>

    <section className="landing-hero brand-hero" id="home">
      <div className="brand-hero__atmosphere" aria-hidden="true"><div className="brand-hero__mesh" /><div className="brand-hero__glow brand-hero__glow--gold" /><div className="brand-hero__glow brand-hero__glow--blue" /><div className="brand-hero__arc" />{Array.from({length:12},(_,i)=><i className="brand-hero__particle" key={i} style={{left:`${8+(i*29)%85}%`,top:`${12+(i*17)%65}%`,animationDelay:`${i*-.8}s`}} />)}</div>
      <div className="landing-container hero-layout">
        <Reveal className="hero-copy">
          <div className="hero-eyebrow"><span /> دعوة رقمية. تجربة متكاملة.</div>
          <h1>من الدعوة<br />إلى <em>الدخول<span className="hero-period">.</span></em></h1>
          <p>امنح ضيوفك بداية تليق بمناسبتك.<br />صمّم دعوات باسم كل ضيف، تابع تأكيد الحضور، ونظّم الدخول عبر QR من منصة واحدة.</p>
          <div className="hero-actions"><Link to="/auth/signup" className="primary-button large">أنشئ حسابك مجانًا <ArrowLeft size={19} /></Link><a href="#platform" className="text-button">كيف تعمل دعوة؟ <span>↙</span></a></div>
          <div className="hero-assurances"><span><Check size={14} /> دعوات باسم كل ضيف</span><span><ShieldCheck size={14} /> دخول موثوق عبر QR</span></div>
        </Reveal>
        <Reveal className="hero-brand-visual" delay={.12}><HeroBrandScene /></Reveal>
      </div>
      <div className="brand-hero__footnote landing-container"><span>DAWAA <i /> THE ART OF ARRIVAL</span><a href="#platform">كل لحظة وصول تبدأ بدعوة <ArrowLeft size={15} /></a></div>
      <div className="capability-rail"><div className="landing-container">{['دعوات رقمية','تأكيد الحضور','رمز دخول مخصص','التحقق من صلاحية الدخول','تنظيم الورديات','متابعة الحضور'].map((item,i)=><span key={item}><i>{String(i+1).padStart(2,'0')}</i>{item}</span>)}</div></div>
    </section>

    <section className="journey-section" id="platform"><div className="landing-container"><Reveal><SectionTitle eyebrow="رحلة واحدة · نظام واحد" title="رحلة مرتبة، من التجهيز إلى الاستقبال." copy="تبدأ بتفاصيل المناسبة، وتستمر بدعوات شخصية وردود واضحة. وعند الوصول، يتحقق فريقك من الدخول ضمن القواعد التي حدّدتها."/></Reveal><div className="journey-line">{journey.map((step,index)=><Reveal className="journey-node" delay={index*.045} key={step}><span>{String(index+1).padStart(2,'0')}</span><strong>{step}</strong></Reveal>)}</div></div></section>

    <section className="studio-section"><div className="landing-container split-grid studio-grid"><Reveal className="showcase-copy"><SectionTitle eyebrow="استوديو التصميم" title="هوية مناسبتك، في كل دعوة." copy="نسّق النصوص والصور والألوان في قالبك، ثم أضف بيانات الضيف ورمز الدخول. تحتفظ الدعوات بهوية واحدة، وتمنح كل ضيف تفاصيله الخاصة."/><div className="variable-list"><span>اسم الضيف</span><span>الجهة</span><span>المقعد</span><span>رمز الدخول</span></div></Reveal><Reveal delay={.08}><DesignStudioPreview/></Reveal></div></section>

    <section className="split-showcase invitations-section" id="invitations"><div className="landing-container split-grid"><Reveal className="showcase-copy"><SectionTitle eyebrow="تجربة الضيف" title="دعوة شخصية. تفاصيل واضحة. وصول أسهل." copy="من لحظة فتح الدعوة، يعرف ضيفك أين ستكون المناسبة ومتى تبدأ، ويؤكد حضوره ويعرض رمز دخوله من الهاتف؛ دون تنزيل تطبيق."/><ul className="feature-lines"><li><Check/>تأكيد الحضور وتحديث حالة الضيف</li><li><Check/>رمز QR مخصص لكل دعوة</li><li><Check/>إضافة الموعد إلى التقويم</li></ul></Reveal><Reveal className="showcase-visual" delay={.08}><InvitationPreview/></Reveal></div></section>

    <section className="field-section" id="operations">
      <div className="landing-container field-layout">
        <Reveal className="field-copy">
          <SectionTitle eyebrow="التشغيل الميداني" title="فريق مستعد، قبل وصول أول ضيف." copy="من تجهيز البوابات إلى استقبال الضيوف، امنح فريقك خطة واضحة ومسؤوليات محددة."/>
          <ol className="field-steps">
            <li><span>01</span><div><h3>جهّز نقاط الدخول</h3><p>حدّد البوابات ومسارات الضيوف قبل الفعالية.</p></div></li>
            <li><span>02</span><div><h3>وزّع الفريق بثقة</h3><p>أسند الأعضاء إلى الورديات، وعيّن مشرفًا لكل بوابة.</p></div></li>
            <li><span>03</span><div><h3>تابع لحظة الوصول</h3><p>راجع الحضور وطلبات المساعدة أثناء الاستقبال.</p></div></li>
          </ol>
          <a className="text-button field-link" href="#gates">اكتشف تجربة المسح والدخول <ArrowLeft size={18}/></a>
        </Reveal>
        <Reveal className="field-image" delay={.08}>
          <figure className="field-photo">
            <img src="/brand/editorial/dawaa-welcome.webp" alt="عضو فريق الاستقبال يتحقق من دعوة ضيف على الهاتف" width="1400" height="933" loading="lazy" decoding="async"/>
            <figcaption><span>من الدعوة إلى الدخول</span><strong>استقبال يليق بضيوفك.</strong><small>صورة توضيحية</small></figcaption>
          </figure>
        </Reveal>
      </div>
    </section>

    <section className="gate-section" id="gates"><div className="landing-container split-grid gate-grid"><Reveal className="showcase-visual"><ScannerPreview/></Reveal><Reveal className="showcase-copy gate-copy" delay={.08}><SectionTitle eyebrow="تشغيل البوابات" title="من قراءة الرمز إلى قرار دخول واضح." copy="يمسح عضو الفريق رمز QR، فيظهر القبول أو سبب الرفض وعدد الأشخاص المتبقي في الدعوة. معلومات تساعده على استقبال الضيف أو طلب مراجعة المشرف."/><div className="gate-features"><div><ShieldCheck/><span><strong>تحقق من صلاحية الدخول</strong><small>وفق سعة الدعوة وقواعد الفعالية</small></span></div><div><WifiOff/><span><strong>حزمة للويب الميداني</strong><small>تُنزّل مسبقًا للعمل دون اتصال</small></span></div><div><Users/><span><strong>مناوبات الفرق</strong><small>توزيع الطاقم على البوابات</small></span></div></div></Reveal></div></section>

    <section className="command-section" id="attendance"><div className="landing-container"><Reveal className="command-heading"><SectionTitle eyebrow="متابعة الحضور" title="تابع الوصول، واتخذ خطوتك التالية." copy="راجع ملخص الحضور وسجل الدخول لمعرفة ما تم تسجيله. صورة أوضح تساعدك على متابعة الاستقبال والتنسيق مع فريق البوابات."/></Reveal><Reveal delay={.08}><CommandCenterPreview/></Reveal></div></section>

    <section id="occasions" className="usecases-section occasions-section"><div className="landing-container">
      <Reveal className="occasions-heading"><SectionTitle eyebrow="مناسبات متعددة · تجربة واحدة متكاملة" title="لكل مناسبة طابعها. ولكل ضيف دعوة تليق به." copy="من اللقاءات المهنية إلى لحظات الاحتفاء، صمّم الدعوة بطابع مناسبتك ورتّب استقبال ضيوفك من مكان واحد."/><a className="occasions-link" href="#invitations">اكتشف تجربة الدعوة <ArrowLeft size={18}/></a></Reveal>
      <div className="occasions-gallery">{useCases.map((item,index)=>{const Icon=item.icon;return <Reveal key={item.title} className={`occasion-card occasion-card-${index}`} delay={index*.04}>
        <div className="occasion-top"><span className="occasion-icon"><Icon size={27} strokeWidth={1.5} aria-hidden="true"/></span><span className="occasion-number" aria-hidden="true">{String(index+1).padStart(2,'0')}</span></div>
        {index===0&&<div className="occasion-stage" aria-hidden="true"><div className="occasion-stage-arch"><Presentation size={58} strokeWidth={1}/></div><div className="occasion-stage-seats">{Array.from({length:12},(_,i)=><i key={i}/>)}</div></div>}
        <div className="occasion-content"><span className="occasion-label">{item.label}</span><h3>{item.title}</h3><p>{item.copy}</p><div className="occasion-tags">{item.tags.map(tag=><span key={tag}>{tag}</span>)}</div></div>
      </Reveal>})}</div>
    </div></section>

    <section className="comparison-section comparison-editorial" id="difference"><div className="landing-container"><Reveal><SectionTitle eyebrow="وضوح في كل مرحلة" title="اجمع تفاصيل المناسبة. وامنح فريقك رؤية أوضح." copy="الدعوة وتأكيد الحضور والاستقبال مراحل مترابطة. إدارتها من مكان واحد تساعدك على متابعة الرحلة كاملة."/></Reveal><div className="comparison-panels"><Reveal className="comparison-panel comparison-panel-connected"><div className="comparison-panel-heading"><BrandLogo symbol/><div><span>رحلة مترابطة</span><h3>مع دعوة</h3></div></div>{comparison.map(([label,value])=><div className="comparison-detail" key={label}><CheckCircle2 size={19}/><div><strong>{label}</strong><p>{value}</p></div></div>)}</Reveal><Reveal className="comparison-panel" delay={.08}><div className="comparison-panel-heading"><LayoutGrid size={32}/><div><span>أدوات منفصلة</span><h3>التشغيل التقليدي</h3></div></div>{comparison.map(([label,,value])=><div className="comparison-detail" key={label}><span className="comparison-dash" aria-hidden="true">—</span><div><strong>{label}</strong><p>{value}</p></div></div>)}</Reveal></div></div></section>

    <section className="getting-started-section onboarding-editorial" id="getting-started"><div className="landing-container"><Reveal><SectionTitle eyebrow="خطوات البدء" title="من فكرة المناسبة إلى خطة استقبال." copy="ابدأ بالتفاصيل الأساسية، ثم جهّز الدعوات والفريق. كل خطوة تمهّد لما بعدها."/></Reveal><div className="getting-started-grid">{gettingStarted.map((step,index)=><Reveal className="getting-started-card" delay={index*.05} key={step.title}><div className="onboarding-step-top"><span>{String(index+1).padStart(2,'0')}</span>{index===0?<CalendarPlus aria-hidden="true"/>:index===1?<Mail aria-hidden="true"/>:<Users aria-hidden="true"/>}</div><h3>{step.title}</h3><p>{step.copy}</p></Reveal>)}</div><Link to="/auth/signup" className="text-button getting-started-link">أنشئ حسابك وابدأ التجهيز <ArrowLeft size={18}/></Link></div></section>

    <section className="pricing-section" id="pricing"><div className="landing-container"><Reveal><SectionTitle eyebrow="الخطط" title="خطة تناسب حجم مناسبتك." copy="راجع المزايا وحدود كل خطة، واختر ما يلائم عدد فعالياتك ودعواتك وأعضاء فريقك."/></Reveal>{plans.length?<div className="pricing-grid">{plans.slice(0,3).map((plan,index)=>{const enterprise=plan.code.toLowerCase()==='enterprise';const free=plan.price_monthly===0;return <Reveal className={`price-plan ${plan.is_popular?'featured':''}`} delay={index*.06} key={plan.id}><div className="plan-head">{plan.is_popular&&<span>الخطة الموصى بها</span>}<small>{plan.name}</small>{enterprise?<strong>تسعير مخصص</strong>:free?<strong>مجانًا</strong>:<strong>${formatUsd(plan.price_monthly)}</strong>}{!enterprise&&!free&&<em>/ شهريًا</em>}{!enterprise&&!free&&<i className="plan-head-yer">≈ {formatYer(plan.price_monthly)} ر.ي</i>}</div><p>{plan.description}</p><ul>{plan.features.slice(0,5).map(feature=><li key={feature}><Check/>{feature}</li>)}</ul><Link to="/auth/signup">اختر الخطة <ArrowLeft/></Link></Reveal>})}</div>:<div className="plans-fallback"><div><strong>خطط مرنة بحسب حجم التشغيل</strong><p>أنشئ حسابك للاطلاع على الأسعار والحدود المعتمدة حاليًا.</p></div><Link to="/auth/signup" className="primary-button">استكشف الخطط <ArrowLeft/></Link></div>}</div></section>

    <section className="faq-section" id="faq"><div className="landing-container faq-grid"><Reveal><SectionTitle eyebrow="الأسئلة الشائعة" title="قبل أن تبدأ، هذه إجاباتك."/></Reveal><div className="faq-list">{faqs.map((faq,index)=>{const open=openFaq===index;return <div className={`faq-item ${open?'open':''}`} key={faq.q}><button type="button" onClick={()=>setOpenFaq(open?null:index)} aria-expanded={open} aria-controls={`faq-answer-${index}`} id={`faq-question-${index}`}><span>{faq.q}</span><ChevronDown/></button><AnimatePresence initial={false}>{open&&<motion.div id={`faq-answer-${index}`} role="region" aria-labelledby={`faq-question-${index}`} initial={{height:0,opacity:0}} animate={{height:'auto',opacity:1}} exit={{height:0,opacity:0}}><p>{faq.a}</p></motion.div>}</AnimatePresence></div>})}</div></div></section>

    <section className="final-cta"><div className="landing-container"><Reveal className="cta-inner"><div className="cta-content"><span>فعاليتك التالية تبدأ من هنا</span><h2>ابدأ بدعوة.<br/>واستعد لاستقبال يليق بضيوفك.</h2><p className="cta-copy">أنشئ حسابك، وجهّز تفاصيل مناسبتك، وامنح كل ضيف بداية شخصية.</p><Link to="/auth/signup" className="primary-button large">ابدأ مجانًا <ArrowLeft/></Link></div><div className="cta-stationery" aria-hidden="true"><div className="cta-envelope"/><div className="cta-note"><BrandLogo symbol/><span>لكل ضيف، بداية تليق به.</span><i/><i/><i/></div></div></Reveal></div></section>
    <footer className="landing-footer"><div className="landing-container footer-grid"><div className="footer-brand"><BrandLogo /><p>دعوات تحمل هوية مناسبتك، وتجربة تجمع تأكيد الحضور وتنظيم الدخول في منصة واحدة.</p></div><div><strong>المنتج</strong><a href="#platform">المنظومة</a><a href="#invitations">الدعوات</a><a href="#gates">البوابات</a></div><div><strong>الحلول</strong><a href="#operations">التشغيل</a><a href="#pricing">الخطط</a><a href="#faq">الأسئلة</a></div><div><strong>الموارد</strong><a href="#faq">الأسئلة الشائعة</a><a href="mailto:support@qentry.app">الدعم</a></div><div><strong>الحساب</strong><Link to="/auth/login">تسجيل الدخول</Link><Link to="/auth/signup">إنشاء حساب</Link></div></div><div className="landing-container footer-bottom"><span>دعوة</span><span>من الدعوة إلى الدخول</span></div></footer>
  </main>
}
