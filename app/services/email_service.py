import smtplib
import logging
from html import escape
from email.utils import formatdate, make_msgid
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _resolve_delivery_recipient(to_email: str) -> str:
    """Avoid Gmail self-delivery de-duplication in local development.

    Gmail can accept repeated SMTP messages sent from an account back to the
    exact same address, then silently collapse or discard them.  A Gmail plus
    alias reaches the same mailbox but is treated as a distinct recipient.
    This is intentionally limited to the local development sender account.
    """
    recipient = (to_email or "").strip().lower()
    sender = (settings.smtp_user or "").strip().lower()
    if settings.app_env.lower() != "development" or recipient != sender:
        return to_email

    local, separator, domain = recipient.partition("@")
    if separator and domain in {"gmail.com", "googlemail.com"} and "+" not in local:
        return f"{local}+qentry-transactional@{domain}"
    return to_email


def _smtp_is_configured() -> bool:
    """Treat placeholder local-development credentials as disabled."""
    smtp_user = (settings.smtp_user or "").strip()
    smtp_pass = (settings.smtp_pass or "").strip()

    if not smtp_user or not smtp_pass:
        return False

    disabled_values = {"disabled", "changeme", "change-me", "example", "localhost"}
    if smtp_pass.lower() in disabled_values:
        return False
    if smtp_user.lower().endswith("@localhost"):
        return False

    return True


def is_email_delivery_configured() -> bool:
    """Return whether this process can submit transactional email to SMTP.

    This deliberately means *configured for submission*, not delivered to the
    recipient.  SMTP does not provide a recipient-delivery guarantee; provider
    webhooks are required to track bounces and final delivery.
    """
    return _smtp_is_configured()


def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    plain_body: Optional[str] = None,
) -> bool:
    """Send an email via SMTP. Returns True on success."""
    if not _smtp_is_configured():
        logger.info("SMTP not configured for delivery; skipping email to %s", to_email)
        return False

    delivery_recipient = _resolve_delivery_recipient(to_email)
    msg = MIMEMultipart("alternative")
    msg["From"] = f"{settings.smtp_sender_name} <{settings.smtp_user}>"
    msg["To"] = delivery_recipient
    msg["Subject"] = subject
    msg["Reply-To"] = settings.smtp_admin_email or settings.smtp_user
    # A fresh RFC-compliant identifier prevents Gmail from treating repeated
    # password-reset notifications as an already-delivered copy.
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="qentry.local")

    if plain_body:
        msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(settings.smtp_user, settings.smtp_pass)
            server.sendmail(settings.smtp_user, delivery_recipient, msg.as_string())
        logger.info("Email sent to %s: %s", delivery_recipient, subject)
        return True
    except Exception as e:
        logger.error("Failed to send email to %s: %s", to_email, str(e))
        return False


# ══════════════════════════════════════════════
# Pre-built email senders
# ══════════════════════════════════════════════

def send_password_reset_email(to_email: str, reset_link: str) -> bool:
    """Send password reset email."""
    subject = "إعادة تعيين كلمة المرور - Qr Platform"
    html = _build_email(
        template="password_reset",
        icon_svg=_ICON_LOCK,
        icon_bg="#fef2f2",
        icon_color="#ef4444",
        preheader="لقد تلقينا طلباً لإعادة تعيين كلمة المرور الخاصة بحسابك",
        heading="إعادة تعيين كلمة المرور",
        paragraphs=[
            "لقد تلقينا طلباً لإعادة تعيين كلمة المرور الخاصة بحسابك على <strong>Qr Platform</strong>.",
            "اضغط على الزر أدناه لإنشاء كلمة مرور جديدة. الرابط صالح لمدة <strong>ساعة واحدة</strong> فقط.",
        ],
        button_text="إعادة تعيين كلمة المرور",
        button_url=reset_link,
        button_bg="#ef4444",
        info_items=[
            ("الجهاز", "متصفح الويب"),
            ("صلاحية الرابط", "ساعة واحدة"),
        ],
        warning_text="إذا لم تطلب إعادة تعيين كلمة المرور، يمكنك تجاهل هذا البريد بأمان. لن يتم إجراء أي تغيير على حسابك.",
        plain_link=reset_link,
    )
    plain = f"إعادة تعيين كلمة المرور\n\nاضغط على الرابط التالي:\n{reset_link}\n\nالرابط صالح لمدة ساعة واحدة."
    return send_email(to_email, subject, html, plain)


def send_invite_email(to_email: str, invite_link: str, tenant_name: str, inviter_name: str) -> bool:
    """Send team invite email."""
    subject = f"دعوة للانضمام إلى {tenant_name} - Qr Platform"
    html = _build_email(
        template="invite",
        icon_svg=_ICON_USERS,
        icon_bg="#eff6ff",
        icon_color="#3b82f6",
        preheader=f"قام {inviter_name} بدعوتك للانضمام إلى {tenant_name}",
        heading=f"دعوة للانضمام إلى {tenant_name}",
        paragraphs=[
            f"قام <strong>{inviter_name}</strong> بدعوتك للانضمام إلى فريق <strong>{tenant_name}</strong> على Qr Platform.",
            "اضغط على الزر أدناه لقبول الدعوة والانضمام إلى الفريق.",
        ],
        button_text="قبول الدعوة",
        button_url=invite_link,
        button_bg="#3b82f6",
        info_items=[
            ("الفريق", tenant_name),
            ("الداعي", inviter_name),
            ("صلاحية الدعوة", "7 أيام"),
        ],
        warning_text="إذا لم تكن تتوقع هذه الدعوة، يمكنك تجاهل هذا البريد بأمان.",
        plain_link=invite_link,
    )
    plain = f"دعوة للانضمام إلى {tenant_name}\n\nقام {inviter_name} بدعوتك.\nاضغط على الرابط: {invite_link}\n\nالدعوة صالحة لمدة 7 أيام."
    return send_email(to_email, subject, html, plain)


def send_welcome_email(to_email: str, full_name: str) -> bool:
    """Send welcome email after signup."""
    name = full_name or "بك"
    subject = "مرحباً بك في Qr Platform!"
    dashboard_url = f"{settings.app_url}/dashboard"
    html = _build_email(
        template="welcome",
        icon_svg=_ICON_ROCKET,
        icon_bg="#f0fdf4",
        icon_color="#22c55e",
        preheader=f"مرحباً {name}! حسابك جاهز على Qr Platform",
        heading=f"أهلاً {name}!",
        paragraphs=[
            "شكراً لتسجيلك في <strong>Qr Platform</strong>. حسابك جاهز الآن!",
            "يمكنك البدء بإنشاء مساحة عمل جديدة، دعوة فريقك، والاستفادة من جميع المميزات.",
        ],
        button_text="ابدأ الآن",
        button_url=dashboard_url,
        button_bg="#22c55e",
        features=[
            ("إنشاء مساحة عمل", "أنشئ مساحة عمل خاصة بفريقك أو مشروعك"),
            ("دعوة الفريق", "أضف أعضاء فريقك بسهولة عبر البريد الإلكتروني"),
            ("إدارة الاشتراكات", "اختر الباقة المناسبة لاحتياجاتك"),
        ],
        warning_text=None,
        plain_link=dashboard_url,
    )
    plain = f"مرحباً {name}!\n\nشكراً لتسجيلك في Qr Platform.\nابدأ من هنا: {dashboard_url}"
    return send_email(to_email, subject, html, plain)


def send_temporary_access_email(
    to_email: str,
    full_name: str,
    tenant_name: str,
    temporary_password: str,
) -> bool:
    """Send credentials for an administrator-created workspace account."""
    name = escape(full_name or "المستخدم")
    workspace = escape(tenant_name or "مساحة العمل")
    safe_password = escape(temporary_password)
    login_url = f"{settings.app_url}/auth/login"
    subject = f"تم إنشاء حسابك في {tenant_name} - Qr Platform"
    html = _build_email(
        template="temporary_access",
        icon_svg=_ICON_LOCK,
        icon_bg="#fffbeb",
        icon_color="#d4a853",
        preheader=f"تم إنشاء حساب لك في {tenant_name}",
        heading=f"مرحباً {name}",
        paragraphs=[
            f"تم إنشاء حساب لك وإضافتك إلى <strong>{workspace}</strong> على Qr Platform.",
            f"البريد: <strong dir=\"ltr\">{escape(to_email)}</strong><br>كلمة المرور المؤقتة: <strong dir=\"ltr\">{safe_password}</strong>",
            "لأمان حسابك، سجّل الدخول ثم غيّر كلمة المرور المؤقتة مباشرة.",
        ],
        button_text="تسجيل الدخول",
        button_url=login_url,
        button_bg="#d4a853",
        warning_text="لا تشارك كلمة المرور مع أي شخص. إذا لم تكن تتوقع هذا الحساب فتواصل مع مسؤول المؤسسة.",
        plain_link=login_url,
    )
    plain = (
        f"مرحباً {full_name or 'المستخدم'}\n\n"
        f"تم إنشاء حسابك في {tenant_name}.\n"
        f"البريد: {to_email}\nكلمة المرور المؤقتة: {temporary_password}\n\n"
        f"سجّل الدخول وغيّر كلمة المرور مباشرة: {login_url}"
    )
    return send_email(to_email, subject, html, plain)


def send_org_request_received(to_email: str, full_name: str, org_name: str) -> bool:
    """Acknowledge an organizer-team registration request."""
    name = full_name or "بك"
    subject = "تم استلام طلب التسجيل - Qr Platform"
    html = _build_email(
        template="org_request_received",
        icon_svg=_ICON_USERS,
        icon_bg="#eff6ff",
        icon_color="#3b82f6",
        preheader="استلمنا طلب تسجيل فريق التنظيم الخاص بك وهو قيد المراجعة",
        heading=f"شكراً {name}!",
        paragraphs=[
            f"استلمنا طلب تسجيل <strong>{org_name}</strong> كفريق تنظيم على <strong>Qr Platform</strong>.",
            "سيقوم فريق المنصة بمراجعة طلبك، وستصلك رسالة عند الموافقة لتتمكن من تسجيل الدخول.",
        ],
        button_text="زيارة المنصة",
        button_url=settings.app_url,
        button_bg="#3b82f6",
        warning_text="لا حاجة لأي إجراء الآن. سنخبرك فور اكتمال المراجعة.",
        plain_link=settings.app_url,
    )
    plain = f"شكراً {name}!\n\nاستلمنا طلب تسجيل {org_name} كفريق تنظيم. طلبك قيد المراجعة وسنخبرك عند الموافقة."
    return send_email(to_email, subject, html, plain)


def send_org_request_approved(to_email: str, full_name: str, org_name: str) -> bool:
    """Notify an applicant that their organizer-team request was approved."""
    name = full_name or "بك"
    subject = "تمت الموافقة على طلبك - Qr Platform"
    login_url = f"{settings.app_url}/auth/login"
    html = _build_email(
        template="org_request_approved",
        icon_svg=_ICON_ROCKET,
        icon_bg="#f0fdf4",
        icon_color="#22c55e",
        preheader=f"تمت الموافقة على {org_name}! يمكنك تسجيل الدخول الآن",
        heading=f"مبارك {name}!",
        paragraphs=[
            f"تمت الموافقة على تسجيل <strong>{org_name}</strong> كفريق تنظيم على <strong>Qr Platform</strong>.",
            "تم تجهيز مساحة العمل الخاصة بك. يمكنك الآن تسجيل الدخول بنفس البريد وكلمة المرور اللذين استخدمتهما في الطلب.",
        ],
        button_text="تسجيل الدخول",
        button_url=login_url,
        button_bg="#22c55e",
        plain_link=login_url,
    )
    plain = f"مبارك {name}!\n\nتمت الموافقة على {org_name}. سجّل الدخول الآن: {login_url}"
    return send_email(to_email, subject, html, plain)


def send_org_request_rejected(to_email: str, full_name: str, org_name: str, reason: str = "") -> bool:
    """Notify an applicant that their organizer-team request was rejected."""
    name = full_name or "بك"
    subject = "بخصوص طلب التسجيل - Qr Platform"
    paragraphs = [
        f"نشكرك على اهتمامك بالتسجيل بـ <strong>{org_name}</strong> على <strong>Qr Platform</strong>.",
        "بعد المراجعة، لم نتمكن من الموافقة على الطلب في الوقت الحالي.",
    ]
    if reason:
        paragraphs.append(f"السبب: {reason}")
    html = _build_email(
        template="org_request_rejected",
        icon_svg=_ICON_SHIELD,
        icon_bg="#fef2f2",
        icon_color="#ef4444",
        preheader="تحديث بخصوص طلب تسجيل فريق التنظيم",
        heading=f"عزيزي {name}",
        paragraphs=paragraphs,
        button_text="التواصل مع الدعم",
        button_url=settings.app_url,
        button_bg="#6366f1",
        warning_text="يمكنك التواصل معنا لمزيد من التفاصيل أو إعادة التقديم لاحقاً.",
        plain_link=settings.app_url,
    )
    plain = f"عزيزي {name}،\n\nلم نتمكن من الموافقة على طلب {org_name} حالياً."
    if reason:
        plain += f"\nالسبب: {reason}"
    return send_email(to_email, subject, html, plain)


def send_password_changed_email(to_email: str) -> bool:
    """Send confirmation that password was changed."""
    subject = "تم تغيير كلمة المرور - Qr Platform"
    login_url = f"{settings.app_url}/login"
    html = _build_email(
        template="password_changed",
        icon_svg=_ICON_SHIELD,
        icon_bg="#f0fdf4",
        icon_color="#22c55e",
        preheader="تم تغيير كلمة المرور الخاصة بحسابك بنجاح",
        heading="تم تغيير كلمة المرور بنجاح",
        paragraphs=[
            "تم تغيير كلمة المرور الخاصة بحسابك على <strong>Qr Platform</strong> بنجاح.",
            "يمكنك الآن تسجيل الدخول باستخدام كلمة المرور الجديدة.",
        ],
        button_text="تسجيل الدخول",
        button_url=login_url,
        button_bg="#6366f1",
        info_items=None,
        warning_text="إذا لم تقم بهذا التغيير، يرجى التواصل مع فريق الدعم فوراً لتأمين حسابك.",
        warning_critical=True,
        plain_link=login_url,
    )
    plain = f"تم تغيير كلمة المرور بنجاح.\n\nإذا لم تقم بهذا التغيير، يرجى التواصل مع الدعم فوراً.\n\nتسجيل الدخول: {login_url}"
    return send_email(to_email, subject, html, plain)


def send_email_verification(to_email: str, verify_link: str) -> bool:
    """Send email verification link."""
    subject = "تأكيد البريد الإلكتروني - Qr Platform"
    html = _build_email(
        template="verify",
        icon_svg=_ICON_MAIL,
        icon_bg="#faf5ff",
        icon_color="#a855f7",
        preheader="يرجى تأكيد بريدك الإلكتروني لإكمال التسجيل",
        heading="تأكيد بريدك الإلكتروني",
        paragraphs=[
            "شكراً لتسجيلك في <strong>Qr Platform</strong>!",
            "يرجى تأكيد بريدك الإلكتروني بالضغط على الزر أدناه لتفعيل حسابك بالكامل.",
        ],
        button_text="تأكيد البريد الإلكتروني",
        button_url=verify_link,
        button_bg="#a855f7",
        info_items=None,
        warning_text="إذا لم تقم بإنشاء حساب على Qr Platform، يمكنك تجاهل هذا البريد بأمان.",
        plain_link=verify_link,
    )
    plain = f"تأكيد البريد الإلكتروني\n\nاضغط على الرابط التالي لتأكيد بريدك:\n{verify_link}"
    return send_email(to_email, subject, html, plain)


def send_otp_email(to_email: str, otp_code: str) -> bool:
    """Send a compact transactional OTP email.

    Password-reset emails should be small and readable in every mail client.
    Keeping this separate from the larger branded template also makes the code
    clear in Gmail's message preview and reduces spam-classification signals.
    """
    subject = "Qentry password reset code"
    title = "\u0631\u0645\u0632 \u0627\u0633\u062a\u0639\u0627\u062f\u0629 \u0643\u0644\u0645\u0629 \u0627\u0644\u0645\u0631\u0648\u0631"
    intro = "\u0627\u0633\u062a\u062e\u062f\u0645 \u0627\u0644\u0631\u0645\u0632 \u0627\u0644\u062a\u0627\u0644\u064a \u0644\u0625\u062a\u0645\u0627\u0645 \u0639\u0645\u0644\u064a\u0629 \u0627\u0644\u0627\u0633\u062a\u0639\u0627\u062f\u0629:"
    expiry = "\u0627\u0644\u0631\u0645\u0632 \u0635\u0627\u0644\u062d \u0644\u0645\u062f\u0629 10 \u062f\u0642\u0627\u0626\u0642 \u0641\u0642\u0637. \u0625\u0630\u0627 \u0644\u0645 \u062a\u0637\u0644\u0628\u0647\u060c \u062a\u062c\u0627\u0647\u0644 \u0647\u0630\u0647 \u0627\u0644\u0631\u0633\u0627\u0644\u0629."
    html = f"""<!doctype html>
<html lang=\"ar\" dir=\"rtl\"><body style=\"margin:0;padding:24px;background:#f8fafc;font-family:Arial,sans-serif;color:#172033\">
  <main style=\"max-width:480px;margin:auto;padding:28px;background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;text-align:right\">
    <h1 style=\"margin:0 0 18px;font-size:22px\">{title}</h1>
    <p style=\"line-height:1.8\">{intro}</p>
    <p dir=\"ltr\" style=\"margin:24px 0;padding:16px;text-align:center;font-size:30px;font-weight:700;letter-spacing:8px;background:#f1f5f9;border-radius:8px\">{otp_code}</p>
    <p style=\"line-height:1.8;color:#475569\">{expiry}</p>
  </main>
</body></html>"""
    plain = f"{title}\n\n{intro}\n\n{otp_code}\n\n{expiry}"
    return send_email(to_email, subject, html, plain)


def send_signup_otp_email(
    to_email: str,
    otp_code: str,
    full_name: str = "",
    organization_name: str = "",
) -> bool:
    """Send a transactional OTP email to confirm a newly created account and workspace."""
    subject = "رمز تفعيل الحساب - Qr Platform"
    name = escape(full_name.strip()) if full_name else ""
    org = escape(organization_name.strip()) if organization_name else ""

    greeting = f"مرحباً {name}،" if name else "مرحباً بك،"
    if org:
        intro = f"{greeting} شكراً لتسجيلك ومؤسستك <strong>{org}</strong> في منصة <strong>Qr Platform</strong>.<br>استخدم رمز التحقق التالي لتأكيد بريدك الإلكتروني وتفعيل حسابك:"
    else:
        intro = f"{greeting} شكراً لتسجيلك في منصة <strong>Qr Platform</strong>.<br>استخدم رمز التحقق التالي لتأكيد بريدك الإلكتروني وتفعيل حسابك:"

    title = "رمز تأكيد الحساب وإنشاء المؤسسة"
    expiry = "الرمز صالح لفترة محدودة. إذا لم تقم بإنشاء حساب في المنصة، يمكنك تجاهل هذه الرسالة بأمان."

    html = f"""<!doctype html>
<html lang="ar" dir="rtl"><body style="margin:0;padding:24px;background:#f8fafc;font-family:Arial,sans-serif;color:#172033">
  <main style="max-width:480px;margin:auto;padding:28px;background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;text-align:right">
    <div style="text-align:center;margin-bottom:20px">
      <span style="display:inline-block;padding:6px 16px;background:#f0fdf4;border-radius:20px;color:#16a34a;font-weight:bold;font-size:14px">Qr Platform</span>
    </div>
    <h1 style="margin:0 0 18px;font-size:20px;color:#0f172a;text-align:center">{title}</h1>
    <p style="line-height:1.8;color:#334155">{intro}</p>
    <p dir="ltr" style="margin:24px 0;padding:16px;text-align:center;font-size:32px;font-weight:700;letter-spacing:8px;background:#f1f5f9;color:#0f172a;border-radius:8px;border:1px solid #cbd5e1">{otp_code}</p>
    <p style="line-height:1.8;color:#64748b;font-size:13px">{expiry}</p>
  </main>
</body></html>"""
    plain = f"{title}\n\n{greeting}\nشكراً لتسجيلك في Qr Platform.\nرمز التحقق الخاص بك هو: {otp_code}\n\n{expiry}"
    return send_email(to_email, subject, html, plain)


def send_event_invitation_email(
    to_email: str,
    invitation_link: str,
    event_title: str,
    guest_name: str = "",
    message: Optional[str] = None,
) -> bool:
    """Submit a guest's event invitation to the configured SMTP relay.

    The caller must only mark its delivery row as ``sent`` after this function
    returns ``True``.  Guest/event fields are escaped before entering the HTML
    template because they are tenant-controlled input.
    """
    title = (event_title or "فعاليتنا").strip()
    name = (guest_name or "").strip()
    custom_message = (message or "").strip()

    safe_title = escape(title)
    safe_name = escape(name)
    safe_message = escape(custom_message).replace("\n", "<br>")

    greeting = f"مرحباً <strong>{safe_name}</strong>،" if safe_name else "مرحباً،"
    paragraphs = [
        greeting,
        f"يسرّنا دعوتك لحضور <strong>{safe_title}</strong>.",
    ]
    if safe_message:
        paragraphs.append(safe_message)
    paragraphs.append("اضغط على الزر أدناه لعرض دعوتك ورمز الدخول الخاص بها.")

    # MIME headers must not contain untrusted line breaks.
    subject_title = " ".join(title.splitlines()) or "فعاليتنا"
    subject = f"دعوة لحضور {subject_title} - Qr Platform"
    html = _build_email(
        template="event_invitation",
        icon_svg=_ICON_MAIL,
        icon_bg="#eff6ff",
        icon_color="#2563eb",
        preheader=f"لديك دعوة لحضور {safe_title}",
        heading=f"دعوة لحضور {safe_title}",
        paragraphs=paragraphs,
        button_text="عرض الدعوة",
        button_url=invitation_link,
        button_bg="#2563eb",
        info_items=[("الفعالية", safe_title)],
        warning_text="إذا لم تكن تتوقع هذه الدعوة، يمكنك تجاهل هذا البريد بأمان.",
        plain_link=invitation_link,
    )
    plain_parts = [
        f"دعوة لحضور {subject_title}",
        f"مرحباً {name}" if name else "مرحباً",
        f"يسرّنا دعوتك لحضور {subject_title}.",
    ]
    if custom_message:
        plain_parts.append(custom_message)
    plain_parts.append(f"عرض الدعوة: {invitation_link}")
    return send_email(to_email, subject, html, "\n\n".join(plain_parts))


def send_booking_request_email(to_email: str, event_title: str, starts_at) -> bool:
    """Notify an organizer team manager about a new booking request."""
    subject = "طلب حجز جديد - Qentry"
    date_text = starts_at.strftime("%Y-%m-%d %H:%M") if hasattr(starts_at, "strftime") else str(starts_at)
    html = f"""
    <div dir="rtl" style="font-family:Arial,sans-serif;line-height:1.8">
      <h2>وصل طلب حجز جديد</h2>
      <p>تم إرسال طلب لتنظيم <strong>{event_title}</strong>.</p>
      <p>موعد الحفل: <strong>{date_text}</strong></p>
      <p>سجّل الدخول إلى لوحة الفريق لمراجعة التفاصيل والقبول أو الرفض.</p>
    </div>"""
    plain = f"وصل طلب حجز جديد لتنظيم {event_title}. الموعد: {date_text}. راجع لوحة الفريق."
    return send_email(to_email, subject, html, plain)


def send_booking_response_email(to_email: str, event_title: str, action: str, note: str | None = None) -> bool:
    """Notify the institution manager when an organizer responds."""
    labels = {"accepted": "تم قبول", "rejected": "تم رفض", "needs_information": "يحتاج معلومات إضافية"}
    label = labels.get(action, action)
    subject = f"{label} طلب الحجز - Qentry"
    note_html = f"<p>ملاحظة الفريق: {note}</p>" if note else ""
    html = f"""
    <div dir="rtl" style="font-family:Arial,sans-serif;line-height:1.8">
      <h2>{label} طلب الحجز</h2>
      <p>الطلب: <strong>{event_title}</strong></p>
      {note_html}
      <p>يمكنك متابعة الحالة من لوحة المؤسسة.</p>
    </div>"""
    plain = f"{label} طلب الحجز: {event_title}." + (f" ملاحظة: {note}" if note else "")
    return send_email(to_email, subject, html, plain)


def send_subscription_upgraded_email(to_email: str, plan_name: str, full_name: str = "") -> bool:
    """Send subscription upgrade confirmation."""
    name = full_name or "العميل"
    subject = f"تم ترقية اشتراكك إلى {plan_name} - Qr Platform"
    dashboard_url = f"{settings.app_url}/dashboard"
    html = _build_email(
        template="subscription",
        icon_svg=_ICON_STAR,
        icon_bg="#fffbeb",
        icon_color="#f59e0b",
        preheader=f"تم ترقية اشتراكك إلى باقة {plan_name}",
        heading=f"تم ترقية اشتراكك إلى {plan_name}!",
        paragraphs=[
            f"مرحباً <strong>{name}</strong>،",
            f"تم ترقية اشتراكك بنجاح إلى باقة <strong>{plan_name}</strong>. يمكنك الآن الاستفادة من جميع المميزات الجديدة.",
        ],
        button_text="استعرض المميزات",
        button_url=dashboard_url,
        button_bg="#f59e0b",
        info_items=[
            ("الباقة الجديدة", plan_name),
        ],
        warning_text=None,
        plain_link=dashboard_url,
    )
    plain = f"تم ترقية اشتراكك إلى {plan_name}.\n\nاستعرض المميزات: {dashboard_url}"
    return send_email(to_email, subject, html, plain)


def send_subscription_request_rejected(to_email: str, full_name: str, plan_name: str, reason: str = "") -> bool:
    """Notify a tenant owner that their plan request was not approved."""
    name = full_name or "بك"
    subject = "بخصوص طلب تغيير الباقة - Qr Platform"
    paragraphs = [
        f"راجعنا طلبك لتفعيل باقة <strong>{plan_name}</strong>.",
        "لم نتمكن من الموافقة عليه في الوقت الحالي.",
    ]
    if reason:
        paragraphs.append(f"السبب: {reason}")
    html = _build_email(
        template="subscription_request_rejected",
        icon_svg=_ICON_SHIELD,
        icon_bg="#fef2f2",
        icon_color="#ef4444",
        preheader="تحديث بخصوص طلب تغيير الباقة",
        heading=f"عزيزي {name}",
        paragraphs=paragraphs,
        button_text="التواصل مع الدعم",
        button_url=settings.app_url,
        button_bg="#6366f1",
        warning_text="يمكنك إرسال طلب جديد في أي وقت بعد تصحيح الملاحظات أعلاه.",
        plain_link=settings.app_url,
    )
    plain = f"عزيزي {name}،\n\nلم نتمكن من الموافقة على طلب باقة {plan_name} حالياً."
    if reason:
        plain += f"\nالسبب: {reason}"
    return send_email(to_email, subject, html, plain)


# ══════════════════════════════════════════════
# SVG Icons (inline, email-safe)
# ══════════════════════════════════════════════

_ICON_LOCK = '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>'

_ICON_USERS = '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>'

_ICON_ROCKET = '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/><path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/><path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/></svg>'

_ICON_SHIELD = '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/></svg>'

_ICON_MAIL = '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/></svg>'

_ICON_STAR = '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a.53.53 0 0 0 .4.29l5.16.754a.53.53 0 0 1 .294.904l-3.733 3.638a.53.53 0 0 0-.152.469l.882 5.14a.53.53 0 0 1-.77.56l-4.614-2.426a.53.53 0 0 0-.494 0L7.14 18.73a.53.53 0 0 1-.77-.56l.882-5.14a.53.53 0 0 0-.152-.47L3.367 8.922a.53.53 0 0 1 .294-.904l5.16-.754a.53.53 0 0 0 .4-.29z"/></svg>'


# ══════════════════════════════════════════════
# Master HTML Template Builder
# ══════════════════════════════════════════════

def _build_email(
    *,
    template: str,
    icon_svg: str,
    icon_bg: str,
    icon_color: str,
    preheader: str,
    heading: str,
    paragraphs: list[str],
    button_text: str,
    button_url: str,
    button_bg: str,
    info_items: Optional[list[tuple[str, str]]] = None,
    features: Optional[list[tuple[str, str]]] = None,
    warning_text: Optional[str] = None,
    warning_critical: bool = False,
    plain_link: Optional[str] = None,
    otp_code: Optional[str] = None,
) -> str:
    """Build a complete, responsive, RTL HTML email."""

    # Info box rows
    info_html = ""
    if info_items:
        rows = ""
        for label, value in info_items:
            rows += f"""
                <tr>
                    <td style="padding:8px 16px;color:#6b7280;font-size:13px;border-bottom:1px solid #f3f4f6;white-space:nowrap;">{label}</td>
                    <td style="padding:8px 16px;color:#1f2937;font-size:13px;font-weight:600;border-bottom:1px solid #f3f4f6;text-align:left;">{value}</td>
                </tr>"""
        info_html = f"""
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f9fafb;border-radius:8px;margin:0 0 24px;border:1px solid #f3f4f6;">
                {rows}
            </table>"""

    # Features list (for welcome email)
    features_html = ""
    if features:
        items = ""
        for feat_title, feat_desc in features:
            items += f"""
                <tr>
                    <td style="padding:12px 16px;border-bottom:1px solid #f3f4f6;">
                        <p style="margin:0 0 2px;color:#1f2937;font-size:14px;font-weight:600;">{feat_title}</p>
                        <p style="margin:0;color:#6b7280;font-size:13px;">{feat_desc}</p>
                    </td>
                </tr>"""
        features_html = f"""
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f9fafb;border-radius:8px;margin:0 0 24px;border:1px solid #f3f4f6;">
                {items}
            </table>"""

    # Warning box
    warning_html = ""
    if warning_text:
        w_bg = "#fef2f2" if warning_critical else "#fffbeb"
        w_border = "#fecaca" if warning_critical else "#fde68a"
        w_icon_color = "#ef4444" if warning_critical else "#f59e0b"
        w_text_color = "#991b1b" if warning_critical else "#92400e"
        w_icon = "&#9888;" if warning_critical else "&#128712;"
        warning_html = f"""
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 24px;">
                <tr>
                    <td style="background-color:{w_bg};border:1px solid {w_border};border-radius:8px;padding:14px 18px;">
                        <p style="margin:0;color:{w_text_color};font-size:13px;line-height:1.7;">
                            <span style="color:{w_icon_color};font-size:16px;margin-left:6px;">{w_icon}</span>
                            {warning_text}
                        </p>
                    </td>
                </tr>
            </table>"""

    # Paragraphs
    paragraphs_html = ""
    for p in paragraphs:
        paragraphs_html += f'<p style="margin:0 0 16px;color:#374151;font-size:15px;line-height:1.8;">{p}</p>'

    # Plain link fallback
    plain_link_html = ""
    if plain_link:
        plain_link_html = f"""
            <p style="margin:24px 0 0;color:#9ca3af;font-size:12px;line-height:1.6;word-break:break-all;">
                إذا لم يعمل الزر، انسخ الرابط التالي في متصفحك:<br>
                <a href="{plain_link}" style="color:#6366f1;text-decoration:underline;">{plain_link}</a>
            </p>"""

    return f"""<!DOCTYPE html>
<html dir="rtl" lang="ar" xmlns="http://www.w3.org/1999/xhtml">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <meta name="color-scheme" content="light">
    <meta name="supported-color-schemes" content="light">
    <title>{heading}</title>
    <!--[if mso]>
    <noscript>
        <xml>
            <o:OfficeDocumentSettings>
                <o:PixelsPerInch>96</o:PixelsPerInch>
            </o:OfficeDocumentSettings>
        </xml>
    </noscript>
    <![endif]-->
</head>
<body style="margin:0;padding:0;background-color:#f3f4f6;font-family:'Segoe UI',Tahoma,Geneva,Verdana,Arial,sans-serif;-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale;">
    <!-- Preheader (hidden preview text) -->
    <div style="display:none;font-size:1px;color:#f3f4f6;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;">
        {preheader}
    </div>

    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#f3f4f6;">
        <tr>
            <td align="center" style="padding:32px 16px;">

                <!-- Logo -->
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;margin-bottom:24px;">
                    <tr>
                        <td align="center" style="padding:0 0 8px;">
                            <h1 style="margin:0;font-size:28px;font-weight:800;color:#6366f1;letter-spacing:-0.5px;">
                                Qr Platform
                            </h1>
                        </td>
                    </tr>
                </table>

                <!-- Main Card -->
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;background-color:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.08),0 4px 24px rgba(0,0,0,0.04);">

                    <!-- Icon + Heading -->
                    <tr>
                        <td style="padding:40px 40px 0;" align="center">
                            <div style="width:64px;height:64px;border-radius:16px;background-color:{icon_bg};display:inline-block;text-align:center;line-height:64px;margin-bottom:24px;">
                                <span style="color:{icon_color};vertical-align:middle;">{icon_svg}</span>
                            </div>
                            <h2 style="margin:0 0 8px;color:#111827;font-size:22px;font-weight:700;line-height:1.4;">{heading}</h2>
                        </td>
                    </tr>

                    <!-- Content -->
                    <tr>
                        <td style="padding:20px 40px 0;">
                            {paragraphs_html}
                        </td>
                    </tr>

                    <!-- Button or OTP Code -->
                    <tr>
                        <td style="padding:8px 40px 24px;" align="center">
                            {f'''
                            <div style="background:linear-gradient(135deg,#6366f1 0%,#8b5cf6 100%);border-radius:16px;padding:28px 20px;margin:8px 0;text-align:center;">
                                <p style="margin:0 0 8px;color:rgba(255,255,255,0.7);font-size:13px;">رمز التحقق الخاص بك</p>
                                <p style="margin:0;font-size:38px;font-weight:800;letter-spacing:12px;color:#ffffff;font-family:monospace;direction:ltr;">{otp_code}</p>
                            </div>
                            ''' if otp_code else f'''
                            <table role="presentation" cellpadding="0" cellspacing="0" border="0">
                                <tr>
                                    <td style="border-radius:10px;background-color:{button_bg};">
                                        <a href="{button_url}" target="_blank" style="display:inline-block;padding:14px 40px;color:#ffffff;font-size:15px;font-weight:700;text-decoration:none;border-radius:10px;letter-spacing:0.3px;mso-padding-alt:0;text-underline-color:#ffffff;">
                                            <!--[if mso]><i style="mso-font-width:150%;mso-text-raise:30px;" hidden>&nbsp;</i><![endif]-->
                                            <span style="mso-text-raise:15px;">{button_text}</span>
                                            <!--[if mso]><i style="mso-font-width:150%;" hidden>&nbsp;</i><![endif]-->
                                        </a>
                                    </td>
                                </tr>
                            </table>
                            '''}
                        </td>
                    </tr>

                    <!-- Info Box -->
                    {"<tr><td style='padding:0 40px 8px;'>" + info_html + "</td></tr>" if info_html else ""}

                    <!-- Features List -->
                    {"<tr><td style='padding:0 40px 8px;'>" + features_html + "</td></tr>" if features_html else ""}

                    <!-- Warning -->
                    {"<tr><td style='padding:0 40px 8px;'>" + warning_html + "</td></tr>" if warning_html else ""}

                    <!-- Plain Link Fallback -->
                    <tr>
                        <td style="padding:0 40px 32px;">
                            {plain_link_html}
                        </td>
                    </tr>

                </table>

                <!-- Footer -->
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;margin-top:24px;">
                    <tr>
                        <td align="center" style="padding:0 40px;">
                            <p style="margin:0 0 8px;color:#9ca3af;font-size:12px;line-height:1.6;">
                                &copy; 2026 Qr Platform. جميع الحقوق محفوظة.
                            </p>
                            <p style="margin:0;color:#d1d5db;font-size:11px;">
                                هذا البريد مرسل من <a href="{settings.app_url}" style="color:#9ca3af;text-decoration:underline;">Qr Platform</a>
                                &nbsp;&bull;&nbsp;
                                <a href="{settings.app_url}/settings/notifications" style="color:#9ca3af;text-decoration:underline;">إدارة الإشعارات</a>
                            </p>
                        </td>
                    </tr>
                </table>

            </td>
        </tr>
    </table>
</body>
</html>"""
