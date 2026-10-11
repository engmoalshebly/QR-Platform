"""Stable API error contract for entitlements, quotas and request throttling.

HTTP statuses remain compatible; clients must branch on detail.code, never
on the translated message or status 429 alone. See docs/LIMIT_ERRORS_API.md.
"""
from fastapi import HTTPException

RESOURCE_NAMES_AR = {
    "events_per_month": "الفعاليات شهرياً",
    "invitations_per_month": "الدعوات شهرياً",
    "invitations_per_event": "الدعوات لكل فعالية",
    "messages_per_month": "الرسائل الشهرية",
    "ai_requests_per_month": "طلبات الذكاء الاصطناعي",
    "monthly_bookings": "طلبات الحجز الشهرية",
    "gates_per_event": "البوابات لكل فعالية",
    "teams_max": "فرق العمل",
    "seats_max": "المقاعد",
    "designed_templates": "القوالب المصممة",
    "guests_max": "الضيوف",
    "registration_forms_max": "نماذج التسجيل النشطة",
    "storage_mb": "التخزين",
    "operations_max": "العمليات",
    "operation_groups_max": "مجموعات الفريق",
    "tasks_per_operation": "مهام العملية",
    "operation_members_max": "أعضاء العملية",
    "attachments_per_operation": "مرفقات العملية",
    "team_members_per_team": "أعضاء الفريق",
}


def plan_limit_exceeded(key: str, current: int, limit: int, requested: int,
                        resource_name: str | None = None, message: str | None = None,
                        **context) -> HTTPException:
    name = resource_name or RESOURCE_NAMES_AR.get(key, key)
    return HTTPException(429, detail={
        "code": "PLAN_LIMIT_EXCEEDED", "limit_key": key,
        "current": int(current), "limit": int(limit), "requested": int(requested),
        "message": message or (
            f"تم تجاوز الحد الأقصى لـ '{name}'. الحالي: {current}، "
            f"المسموح به: {limit}، المطلوب: {requested}."
        ), **context,
    })


def limit_not_configured(key: str) -> HTTPException:
    return HTTPException(402, detail={
        "code": "PLAN_LIMIT_NOT_CONFIGURED", "limit_key": key,
        "message": "تعذر تنفيذ العملية لأن حد المورد غير مهيأ. يرجى التواصل مع الدعم.",
    })


def feature_not_included(key: str, *, disabled: bool = False) -> HTTPException:
    return HTTPException(403, detail={
        "code": "FEATURE_DISABLED" if disabled else "FEATURE_NOT_INCLUDED",
        "feature_key": key,
        "message": ("هذه الميزة معطلة لهذا الحساب. يرجى التواصل مع مسؤول الحساب." if disabled
                    else "هذه الميزة غير مشمولة في باقتك الحالية. يرجى مراجعة الباقات."),
    })


def event_quota_exceeded(event_id: str, ticket_class: str, current: int,
                         limit: int, requested: int) -> HTTPException:
    return HTTPException(400, detail={
        "code": "EVENT_QUOTA_EXCEEDED", "event_id": str(event_id),
        "limit_key": "vip_quota" if ticket_class == "vip" else "normal_quota",
        "ticket_class": ticket_class, "current": int(current), "limit": int(limit),
        "requested": int(requested),
        "message": f"تم الوصول للحد الأقصى لدعوات {ticket_class} ({limit}). "
                   f"المستخدم: {current}، المطلوب: {requested}، المتبقي: {max(0, limit - current)}",
    })


def rate_limit_detail(limit: int, retry_after: int = 60) -> dict:
    return {"code": "RATE_LIMIT_EXCEEDED", "limit": limit,
            "retry_after": retry_after,
            "message": "تم تجاوز حد الطلبات المسموح به. يرجى المحاولة لاحقاً."}


def usage_busy(key: str, retry_after: int = 5) -> HTTPException:
    """Another request holds the account's usage lock (e.g. a large generation).

    The reservation lock is transactional, so a long generation keeps it until
    commit.  Waiting is bounded (see usage_lock_wait_seconds) and surfaces here
    instead of hanging until a proxy timeout while holding a database connection.
    """
    return HTTPException(409, detail={
        "code": "USAGE_BUSY", "limit_key": key, "retry_after": int(retry_after),
        "message": "عملية أخرى على هذا الحساب قيد التنفيذ حالياً. أعد المحاولة بعد لحظات.",
    }, headers={"Retry-After": str(int(retry_after))})
