import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { AnimatePresence, motion, useReducedMotion, useScroll, useSpring } from 'framer-motion'
import { ArrowLeft, ArrowUpLeft, CalendarPlus, Check, CheckCircle2, ChevronDown, Clock3, Menu, Radio, ShieldCheck, Signal, Users, WifiOff, X } from 'lucide-react'
import { subscriptionsAPI, type Plan } from '@features/settings/api/subscriptionsApi'
import { LocalQrCode } from '@shared/components/LocalQrCode'
import './landing.css'

const journey = ['إنشاء الفعالية', 'إرسال الدعوة', 'تأكيد الحضور', 'الوصول', 'التحقق', 'الدخول', 'المتابعة']
const useCases = ['المؤتمرات', 'المعارض', 'حفلات التخرج', 'فعاليات الشركات', 'المناسبات الخاصة']
const comparison = [
  ['الدعوات', 'إرسال ومتابعة من مكان واحد', 'ملفات ورسائل منفصلة'],
  ['الدخول', 'تحقق مباشر من حالة الضيف', 'قوائم ورقية أو بحث يدوي'],
  ['الأجهزة', 'هواتف فريق التنظيم', 'أجهزة خاصة لكل نقطة'],
  ['الاتصال', 'وضع تشغيل دون اتصال', 'توقف عند ضعف الشبكة'],
  ['التكرار', 'تنبيه عند إعادة استخدام الدعوة', 'يصعب اكتشافه لحظيًا'],
  ['المتابعة', 'حالة البوابات في لوحة واحدة', 'اتصالات وتحديثات متفرقة'],
]
const faqs = [
  { q: 'هل يحتاج الضيف إلى تطبيق؟', a: 'لا. يفتح الضيف رابط الدعوة من هاتفه ويستطيع مراجعة التفاصيل وتأكيد الحضور وعرض رمز الدخول من المتصفح.' },
  { q: 'كيف تمنع Qentry استخدام الدعوة أكثر من مرة؟', a: 'يتحقق نظام البوابة من حالة الدعوة عند كل عملية مسح ويعرض تنبيهًا واضحًا إذا سبق تسجيل الدخول بها.' },
  { q: 'هل تعمل البوابات عند ضعف الاتصال؟', a: 'يدعم تطبيق البوابات وضع التشغيل دون اتصال، ثم يزامن عمليات الدخول عند عودة الشبكة.' },
  { q: 'هل يمكن تصميم الدعوات والبطاقات داخل المنصة؟', a: 'نعم. يتيح محرر التصميم إضافة عناصر ثابتة ومتغيرات الضيف ورمز QR إلى الدعوات والبطاقات.' },
  { q: 'هل يمكن إدارة عدة بوابات وفرق؟', a: 'نعم. يمكنك إنشاء البوابات وتوزيع المناوبات والمسؤوليات ومتابعة حالة الدخول من لوحة العمليات.' },
]

function Reveal({ children, className = '', delay = 0 }: { children: ReactNode; className?: string; delay?: number }) {
  const reduced = useReducedMotion()
  return <motion.div className={className} initial={reduced ? false : { opacity: 0, y: 24 }} whileInView={reduced ? undefined : { opacity: 1, y: 0 }} viewport={{ once: true, amount: .15 }} transition={{ duration: .65, delay, ease: [0.16, 1, 0.3, 1] }}>{children}</motion.div>
}

function SectionTitle({ eyebrow, title, copy }: { eyebrow: string; title: string; copy?: string }) {
  return <div className="landing-section-title"><span>{eyebrow}</span><h2>{title}</h2>{copy && <p>{copy}</p>}</div>
}

function HeroOperationsPreview() {
  return <div className="hero-product" aria-label="معاينة توضيحية لمركز العمليات">
    <div className="hero-product-bar"><div className="hero-product-title"><span className="live-dot" /> مركز عمليات الفعالية</div><span className="demo-label">بيانات توضيحية</span></div>
    <div className="hero-product-body">
      <aside className="hero-side"><img src="/logo-alt.png" alt="" /><span className="hero-side-active">نظرة عامة</span><span>الضيوف</span><span>البوابات</span><span>الفريق</span></aside>
      <div className="hero-console">
        <div className="hero-console-head"><div><small>الفعالية الحالية</small><strong>ملتقى الابتكار</strong></div><span><Radio size={14} /> مباشر</span></div>
        <div className="hero-metrics"><div><small>تم الدخول</small><strong>248</strong><i>ضيف</i></div><div><small>البوابات</small><strong>04</strong><i>نشطة</i></div><div><small>آخر دقيقة</small><strong>18</strong><i>عملية</i></div></div>
        <div className="hero-activity"><div className="activity-head"><strong>حركة الدخول</strong><span>آخر 30 دقيقة</span></div><div className="activity-chart" aria-hidden="true">{[26,38,32,54,48,70,58,82,67,91,78,96].map((height,i)=><i key={i} style={{height:`${height}%`}} />)}</div></div>
        <div className="hero-feed"><div><span className="avatar">ن</span><p><strong>نورة القحطاني</strong><small>البوابة الرئيسية · الآن</small></p><em>تم الدخول</em></div><div><span className="avatar alternate">م</span><p><strong>محمد العتيبي</strong><small>بوابة كبار الضيوف · منذ دقيقة</small></p><em>تم الدخول</em></div></div>
      </div>
    </div>
    <div className="hero-invite-float"><small>دعوة ضيف</small><strong>نورة القحطاني</strong><span>ملتقى الابتكار</span><div><LocalQrCode value="QENTRY-HERO-DEMO" size={66} alt="رمز دعوة توضيحي" /></div></div>
    <div className="hero-scan-float"><span><Check size={18}/></span><div><small>بوابة 01</small><strong>تم التحقق</strong></div></div>
  </div>
}

function InvitationPreview() {
  return <div className="invitation-scene" aria-label="معاينة دعوة رقمية"><div className="phone-frame"><div className="phone-status"><span>9:41</span><Signal size={13}/></div><div className="invite-cover"><span>QENTRY</span><small>يدعوكم إلى</small><h3>ملتقى<br/>الابتكار</h3><p>الخميس، 24 سبتمبر · 7:30 مساءً</p></div><div className="invite-guest"><small>هذه الدعوة خاصة بـ</small><strong>نورة القحطاني</strong></div><div className="invite-qr"><LocalQrCode value="QENTRY-GUEST-DEMO" size={92} alt="رمز دعوة توضيحي"/></div><div className="invite-actions"><button type="button">تأكيد الحضور</button><button type="button"><CalendarPlus size={16}/> التقويم</button></div></div><div className="invite-confirm"><CheckCircle2 size={18}/><span><strong>تم تأكيد الحضور</strong><small>تحدّثت الحالة في لوحة العمليات</small></span></div></div>
}

function ScannerPreview() {
  return <div className="scanner-shell" aria-label="معاينة واجهة مسح رمز الدخول"><div className="scanner-top"><span>البوابة الرئيسية</span><strong><span/> متصل</strong></div><div className="scanner-camera"><div className="scanner-corners"/><div className="scanner-line"/><div className="scanner-code"><LocalQrCode value="QENTRY-SCAN-DEMO" size={122} alt="رمز دخول توضيحي"/></div></div><div className="scanner-result"><span><Check size={22}/></span><div><small>تم التحقق من الدعوة</small><strong>نورة القحطاني</strong><p>VIP · ضيف واحد</p></div><em>سماح بالدخول</em></div><div className="scanner-duplicate"><ShieldCheck size={17}/><span><strong>Anti-passback</strong> يظهر تنبيه عند تكرار المسح</span></div></div>
}

function CommandCenterPreview() {
  return <div className="command-ui" aria-label="معاينة توضيحية لمركز العمليات"><div className="command-top"><div><span className="live-dot"/> تشغيل مباشر</div><small>بيانات العرض توضيحية</small></div><div className="command-grid"><div className="command-main"><div className="command-kpis"><div><span>الدخول</span><strong>248</strong><small>ضيف</small></div><div><span>المتبقي</span><strong>132</strong><small>دعوة</small></div><div><span>الفريق</span><strong>12</strong><small>متصل</small></div></div><div className="command-chart"><div><strong>حركة الوصول</strong><small>تحديث مباشر</small></div><svg viewBox="0 0 600 170" role="img" aria-label="رسم توضيحي لحركة الوصول"><defs><linearGradient id="chartFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#d8b66d" stopOpacity=".28"/><stop offset="1" stopColor="#d8b66d" stopOpacity="0"/></linearGradient></defs><path className="chart-area" d="M0 145 C55 132 72 118 120 124 S196 76 250 98 S330 42 385 68 S470 28 520 44 S570 18 600 22 L600 170 L0 170Z"/><path className="chart-line" d="M0 145 C55 132 72 118 120 124 S196 76 250 98 S330 42 385 68 S470 28 520 44 S570 18 600 22"/></svg></div></div><div className="gate-status"><div className="gate-status-head"><strong>حالة البوابات</strong><span>4 / 4</span></div>{['البوابة الرئيسية','بوابة VIP','البوابة الشرقية','مدخل الفريق'].map((gate,index)=><div className="gate-row" key={gate}><span><i/>{gate}</span><strong>{[104,72,54,18][index]}</strong></div>)}<div className="ops-alert"><Clock3 size={17}/><span><strong>ذروة وصول متوقعة</strong><small>خلال 15 دقيقة</small></span></div></div></div></div>
}

function DesignStudioPreview() {
  return <div className="studio-ui" aria-label="معاينة محرر تصميم الدعوات"><div className="studio-top"><strong>محرر بطاقة الضيف</strong><button type="button">حفظ القالب</button></div><div className="studio-body"><aside><span className="active">النصوص</span><span>الصور</span><span>QR</span><span>الخلفية</span></aside><div className="studio-canvas"><div className="design-card"><small>ملتقى الابتكار</small><h3>{'{{guest_name}}'}</h3><p>{'{{company}}'} · المقعد {'{{seat}}'}</p><div><LocalQrCode value="QENTRY-DESIGN-DEMO" size={74} alt="رمز QR داخل القالب"/></div></div></div><div className="studio-props"><strong>المتغيرات</strong>{['guest_name','company','seat','qr_code'].map(item=><button key={item} type="button">{`{{${item}}}`}</button>)}</div></div></div>
}

export default function LandingPage() {
  const [scrolled,setScrolled]=useState(false), [menuOpen,setMenuOpen]=useState(false), [openFaq,setOpenFaq]=useState<number|null>(0), [plans,setPlans]=useState<Plan[]>([])
  const { scrollYProgress } = useScroll()
  const progress = useSpring(scrollYProgress,{stiffness:150,damping:28,mass:.25})
  useEffect(()=>{const handle=()=>setScrolled(window.scrollY>24);window.addEventListener('scroll',handle,{passive:true});document.title='Qentry | منصة تشغيل الفعاليات';return()=>window.removeEventListener('scroll',handle)},[])
  useEffect(()=>{let mounted=true;subscriptionsAPI.listPlans().then(items=>{if(mounted)setPlans(items.filter(p=>p.is_active).sort((a,b)=>a.sort_order-b.sort_order))}).catch(()=>undefined);return()=>{mounted=false}},[])
  const closeMenu=()=>setMenuOpen(false)
  return <main className="landing" dir="rtl">
    <motion.div className="scroll-progress" style={{scaleX:progress}} aria-hidden="true"/>
    <header className={`landing-header ${scrolled?'is-scrolled':''}`}><nav className="landing-nav" aria-label="التنقل الرئيسي"><a href="#home" className="landing-logo" aria-label="Qentry الرئيسية"><img src="/logo.svg" alt="Qentry"/></a><div id="landing-menu" className={`landing-links ${menuOpen?'is-open':''}`}><a href="#platform" onClick={closeMenu}>المنظومة</a><a href="#invitations" onClick={closeMenu}>الدعوات</a><a href="#gates" onClick={closeMenu}>البوابات</a><a href="#operations" onClick={closeMenu}>التشغيل الميداني</a><a href="#pricing" onClick={closeMenu}>الأسعار</a></div><div className="landing-actions"><Link to="/auth/login" className="login-link">تسجيل الدخول</Link><Link to="/auth/signup" className="primary-button">ابدأ مجانًا <ArrowUpLeft size={17}/></Link></div><button className="menu-button" type="button" onClick={()=>setMenuOpen(v=>!v)} aria-expanded={menuOpen} aria-controls="landing-menu" aria-label={menuOpen?'إغلاق القائمة':'فتح القائمة'}>{menuOpen?<X/>:<Menu/>}</button></nav></header>

    <section className="landing-hero" id="home"><div className="landing-container hero-layout"><motion.div className="hero-copy" initial={{opacity:0,y:24}} animate={{opacity:1,y:0}} transition={{duration:.7}}><div className="hero-eyebrow"><span/> منصة تشغيل الفعاليات</div><h1>من الدعوة<br/>إلى <em>الدخول.</em></h1><p>أدر رحلة الضيف كاملة، وشغّل بوابات الدخول والفرق الميدانية من منصة واحدة متصلة.</p><div className="hero-actions"><Link to="/auth/signup" className="primary-button large">ابدأ مجانًا <ArrowLeft size={19}/></Link><a href="#platform" className="text-button">اكتشف المنظومة <span>↓</span></a></div></motion.div><motion.div initial={{opacity:0,x:-28}} animate={{opacity:1,x:0}} transition={{duration:.8,delay:.12}}><HeroOperationsPreview/></motion.div></div><div className="capability-rail"><div className="landing-container">{['دعوات رقمية','RSVP','QR Validation','Anti-passback','Offline Scanning','Live Operations'].map((item,i)=><span key={item}><i>{String(i+1).padStart(2,'0')}</i>{item}</span>)}</div></div></section>

    <section className="journey-section" id="platform"><div className="landing-container"><Reveal><SectionTitle eyebrow="رحلة واحدة · نظام واحد" title="كل خطوة متصلة بما بعدها." copy="من إعداد الفعالية حتى آخر ضيف يعبر البوابة، تبقى البيانات والفرق وحالة الدخول في سياق واحد."/></Reveal><div className="journey-line">{journey.map((step,index)=><Reveal className="journey-node" delay={index*.045} key={step}><span>{String(index+1).padStart(2,'0')}</span><strong>{step}</strong></Reveal>)}</div></div></section>

    <section className="split-showcase invitations-section" id="invitations"><div className="landing-container split-grid"><Reveal className="showcase-copy"><SectionTitle eyebrow="تجربة الضيف" title="دعوة مصممة للوصول، والرد، والدخول." copy="يحصل كل ضيف على رابط دعوة خاص به، وتفاصيل واضحة، ورمز دخول مرتبط بسجل حضوره."/><ul className="feature-lines"><li><Check/>تأكيد الحضور وتحديث حالة الضيف</li><li><Check/>رمز QR مخصص لكل دعوة</li><li><Check/>إضافة الموعد إلى التقويم</li></ul></Reveal><Reveal className="showcase-visual" delay={.08}><InvitationPreview/></Reveal></div></section>

    <section className="gate-section" id="gates"><div className="landing-container split-grid gate-grid"><Reveal className="showcase-visual"><ScannerPreview/></Reveal><Reveal className="showcase-copy gate-copy" delay={.08}><SectionTitle eyebrow="تشغيل البوابات" title="قرار واضح في لحظة المسح." copy="واجهة ميدانية تبيّن للمنظم فورًا إن كانت الدعوة صالحة أو مستخدمة سابقًا، مع استمرار العمل عند انقطاع الاتصال."/><div className="gate-features"><div><ShieldCheck/><span><strong>منع الدخول المتكرر</strong><small>حالة فورية لكل دعوة</small></span></div><div><WifiOff/><span><strong>تشغيل دون اتصال</strong><small>مزامنة عند عودة الشبكة</small></span></div><div><Users/><span><strong>مناوبات الفرق</strong><small>توزيع الطاقم على البوابات</small></span></div></div></Reveal></div></section>

    <section className="command-section" id="operations"><div className="landing-container"><Reveal className="command-heading"><SectionTitle eyebrow="Command Center" title="شاهد الفعالية وهي تتحرك." copy="تابع حركة الضيوف، ضغط البوابات، وحالة الفرق من واجهة تشغيل واحدة."/></Reveal><Reveal delay={.08}><CommandCenterPreview/></Reveal></div></section>

    <section className="studio-section"><div className="landing-container split-grid studio-grid"><Reveal className="showcase-copy"><SectionTitle eyebrow="استوديو التصميم" title="صمّم بطاقة كاملة، لا مجرد رمز QR." copy="ابنِ قوالب الدعوات والبطاقات داخل المنصة، واربط التصميم مباشرة ببيانات كل ضيف."/><div className="variable-list"><span>{'{{guest_name}}'}</span><span>{'{{company}}'}</span><span>{'{{seat}}'}</span><span>{'{{qr_code}}'}</span></div></Reveal><Reveal delay={.08}><DesignStudioPreview/></Reveal></div></section>

    <section className="field-section"><div className="landing-container"><Reveal><SectionTitle eyebrow="التشغيل الميداني" title="الفريق يعرف أين يكون، وماذا يفعل." copy="نظّم البوابات والمناوبات والمهام والمسؤوليات داخل خطة تشغيل واضحة."/></Reveal><div className="ops-flow"><Reveal className="ops-stage"><span>01</span><div><small>قبل الفعالية</small><strong>إعداد البوابات</strong><p>تعريف نقاط الدخول ومسارات الضيوف</p></div></Reveal><Reveal className="ops-stage" delay={.05}><span>02</span><div><small>توزيع الفريق</small><strong>المناوبات والمسؤوليات</strong><p>إسناد كل عضو إلى موقع ومهمة</p></div></Reveal><Reveal className="ops-stage" delay={.1}><span>03</span><div><small>أثناء التشغيل</small><strong>متابعة الحالة</strong><p>تنبيهات وحركة دخول في الوقت الفعلي</p></div></Reveal></div></div></section>

    <section className="usecases-section"><div className="landing-container usecases-grid"><Reveal><SectionTitle eyebrow="حالات الاستخدام" title="مسار تشغيل يناسب شكل فعاليتك."/></Reveal><div className="usecases-list">{useCases.map((item,index)=><Reveal key={item} className="usecase-row" delay={index*.035}><span>{String(index+1).padStart(2,'0')}</span><strong>{item}</strong><ArrowUpLeft/></Reveal>)}</div></div></section>

    <section className="comparison-section"><div className="landing-container"><Reveal><SectionTitle eyebrow="Qentry مقابل التشغيل التقليدي" title="من خطوات متفرقة إلى عملية واحدة واضحة." copy="تجمع Qentry الدعوات والدخول والمتابعة التشغيلية في مسار متصل بدل التنقل بين أدوات وقوائم منفصلة."/></Reveal><Reveal className="comparison-table" delay={.08}><div className="comparison-head"><span>العملية</span><strong>مع Qentry</strong><span>التشغيل التقليدي</span></div>{comparison.map(([label,qentry,traditional])=><div className="comparison-row" key={label}><strong>{label}</strong><span className="comparison-qentry"><CheckCircle2/>{qentry}</span><span>{traditional}</span></div>)}</Reveal></div></section>

    <section className="pricing-section" id="pricing"><div className="landing-container"><Reveal><SectionTitle eyebrow="الخطط" title="ابدأ بما تحتاجه الآن." copy="تأتي تفاصيل الأسعار والحدود مباشرة من الخطط المعتمدة في المنصة."/></Reveal>{plans.length?<div className="pricing-grid">{plans.slice(0,3).map((plan,index)=>{const enterprise=plan.code.toLowerCase()==='enterprise';const price=enterprise?'تسعير مخصص':plan.price_monthly===0?'مجانًا':`${plan.price_monthly.toLocaleString('en-US')} ${plan.currency}`;return <Reveal className={`price-plan ${plan.is_popular?'featured':''}`} delay={index*.06} key={plan.id}><div className="plan-head">{plan.is_popular&&<span>الخطة الموصى بها</span>}<small>{plan.name}</small><strong>{price}</strong>{!enterprise&&plan.price_monthly!==0&&<em>/ شهريًا</em>}</div><p>{plan.description}</p><ul>{plan.features.slice(0,5).map(feature=><li key={feature}><Check/>{feature}</li>)}</ul><Link to="/auth/signup">اختر الخطة <ArrowLeft/></Link></Reveal>})}</div>:<div className="plans-fallback"><div><strong>خطط مرنة بحسب حجم التشغيل</strong><p>أنشئ حسابك للاطلاع على الأسعار والحدود المعتمدة حاليًا.</p></div><Link to="/auth/signup" className="primary-button">استكشف الخطط <ArrowLeft/></Link></div>}</div></section>

    <section className="faq-section" id="faq"><div className="landing-container faq-grid"><Reveal><SectionTitle eyebrow="الأسئلة الشائعة" title="قبل أن تبدأ."/></Reveal><div className="faq-list">{faqs.map((faq,index)=>{const open=openFaq===index;return <div className={`faq-item ${open?'open':''}`} key={faq.q}><button type="button" onClick={()=>setOpenFaq(open?null:index)} aria-expanded={open}><span>{faq.q}</span><ChevronDown/></button><AnimatePresence initial={false}>{open&&<motion.div initial={{height:0,opacity:0}} animate={{height:'auto',opacity:1}} exit={{height:0,opacity:0}}><p>{faq.a}</p></motion.div>}</AnimatePresence></div>})}</div></div></section>

    <section className="final-cta"><div className="landing-container"><Reveal className="cta-inner"><span>فعاليتك التالية تبدأ من هنا</span><h2>شغّل رحلة الضيف كاملة<br/>بوضوح أكبر.</h2><Link to="/auth/signup" className="primary-button large">ابدأ مجانًا <ArrowLeft/></Link></Reveal></div></section>
    <footer className="landing-footer"><div className="landing-container footer-grid"><div className="footer-brand"><img src="/logo.svg" alt="Qentry"/><p>منصة لإدارة الفعاليات والدعوات الرقمية وتشغيل بوابات الدخول.</p></div><div><strong>المنتج</strong><a href="#platform">المنظومة</a><a href="#invitations">الدعوات</a><a href="#gates">البوابات</a></div><div><strong>الحلول</strong><a href="#operations">التشغيل</a><a href="#pricing">الخطط</a><a href="#faq">الأسئلة</a></div><div><strong>الموارد</strong><a href="#faq">الأسئلة الشائعة</a><a href="mailto:support@qentry.app">الدعم</a></div><div><strong>الحساب</strong><Link to="/auth/login">تسجيل الدخول</Link><Link to="/auth/signup">إنشاء حساب</Link></div></div><div className="landing-container footer-bottom"><span>Qentry</span><span>Event Operations Platform</span></div></footer>
  </main>
}
