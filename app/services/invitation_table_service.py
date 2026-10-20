"""Bounded event invitation pages; filters and totals cover the whole scope."""
from dataclasses import dataclass
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import text
from app.models.invitation import InvitationRead
from app.services import whatsapp_service as wa


@dataclass(frozen=True)
class TableFilters:
    event_id: UUID
    tab: str = 'rsvp'
    search: str = ''
    ticket_class: str = 'all'
    rsvp_status: str = 'all'
    checkin: str = 'all'
    whatsapp_state: str = 'all'


PURPOSE_SQL = """CASE WHEN (lower(i.metadata->>'require_rsvp')='true'
    OR (NOT(COALESCE(i.metadata,'{}'::jsonb) ? 'require_rsvp') AND i.rsvp_status IN ('pending','maybe')))
    AND i.rsvp_status IS DISTINCT FROM 'accepted' THEN 'rsvp' ELSE 'ticket' END"""


def scope_where(tenant_id, filters):
    if filters.tab not in ('rsvp','final'):
        raise HTTPException(422, 'تبويب غير صالح.')
    where = """i.tenant_id=:tid AND i.event_id=:eid
        AND i.metadata->>'generation_deleted' IS DISTINCT FROM 'true'"""
    params = {'tid': str(tenant_id), 'eid': str(filters.event_id)}
    if filters.tab == 'final':
        where += " AND i.rsvp_status='accepted'"
    else:
        where += """ AND CASE
            WHEN lower(i.metadata->>'require_rsvp')='true' THEN true
            WHEN lower(i.metadata->>'require_rsvp')='false' THEN false
            WHEN i.is_registration OR lower(i.metadata->>'is_registration')='true' THEN false
            ELSE i.rsvp_status IN ('pending','maybe','declined') OR
                (i.rsvp_status='accepted' AND i.status IN ('viewed','sent','created')) END"""
    return where, params


def filtered_query(tenant_id, filters):
    where, params = scope_where(tenant_id, filters)
    join = ''
    q = filters.search.strip()
    if q:
        escaped = q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        params['search'] = '%' + escaped + '%'
        where += """ AND (i.guest_name ILIKE :search OR i.guest_name_ar ILIKE :search
            OR i.guest_phone ILIKE :search OR i.guest_whatsapp ILIKE :search OR i.token ILIKE :search)"""
    if filters.ticket_class != 'all':
        where += ' AND i.ticket_class=:tc'; params['tc'] = filters.ticket_class
    if filters.rsvp_status != 'all':
        if filters.rsvp_status == 'pending':
            where += " AND COALESCE(i.rsvp_status,'pending') IN ('pending','maybe')"
        else:
            where += ' AND i.rsvp_status=:rs'; params['rs'] = filters.rsvp_status
    if filters.checkin != 'all':
        where += ' AND COALESCE(i.checkin_count,0)' + ('>0' if filters.checkin == 'checked_in' else '=0')
    if filters.whatsapp_state != 'all':
        join = f""" LEFT JOIN LATERAL (SELECT d.state FROM whatsapp_deliveries d
            WHERE d.tenant_id=:tid AND d.event_id=:eid AND d.invitation_id=i.id AND d.purpose=({PURPOSE_SQL})
            ORDER BY d.created_at DESC,d.id DESC LIMIT 1) latest ON true"""
        if filters.whatsapp_state == 'not_sent':
            where += ' AND latest.state IS NULL'
        elif filters.whatsapp_state == 'sent':
            where += " AND latest.state IN ('sent','delivered','read')"
        elif filters.whatsapp_state == 'pending':
            where += " AND latest.state IN ('queued','waiting_connection','sending')"
        else:
            where += ' AND latest.state=:ws'; params['ws'] = filters.whatsapp_state
    return join, where, params


async def stats(db, tenant_id, filters):
    where, params = scope_where(tenant_id, filters)
    row = (await db.execute(text(f"""SELECT COUNT(*) total,
        COUNT(*) FILTER (WHERE rsvp_status='accepted') accepted,
        COUNT(*) FILTER (WHERE rsvp_status='declined') declined,
        COUNT(*) FILTER (WHERE COALESCE(rsvp_status,'pending') NOT IN ('accepted','declined')) pending,
        COALESCE(SUM(plus_one_count) FILTER (WHERE rsvp_status='accepted'),0) AS "plusOnes",
        COUNT(*) FILTER (WHERE status IN ('viewed','accepted','declined','checked_in')) viewed,
        COUNT(*) FILTER (WHERE status='sent') sent,
        COUNT(*) FILTER (WHERE status='created') unopened,
        COUNT(*) FILTER (WHERE ticket_class='vip') vip,
        COUNT(*) FILTER (WHERE ticket_class IS DISTINCT FROM 'vip') normal,
        COUNT(*) FILTER (WHERE COALESCE(checkin_count,0)>0) AS "checkedIn",
        COUNT(*) FILTER (WHERE COALESCE(checkin_count,0)=0) remaining
        FROM invitations i WHERE {where}"""), params)).mappings().one()
    return {key: int(value) for key,value in row.items()}


async def page(db, tenant_id, filters, limit=50, offset=0, can_view_whatsapp=False):
    join, where, params = filtered_query(tenant_id, filters)
    total = (await db.execute(text(f'SELECT COUNT(*) FROM invitations i {join} WHERE {where}'), params)).scalar_one()
    # The last page can disappear after a reply or cancellation. Return a valid
    # page instead of leaving the operator stranded on an empty old offset.
    offset = min(offset, ((max(total,1)-1)//limit)*limit)
    rows = (await db.execute(text(f'''SELECT i.* FROM invitations i {join} WHERE {where}
        ORDER BY i.created_at DESC,i.id DESC LIMIT :limit OFFSET :offset'''),
        {**params,'limit':limit,'offset':offset})).mappings().all()
    items = [InvitationRead(**dict(row)) for row in rows]
    summary = await wa.read_summary(db, tenant_id, filters.event_id, [row['id'] for row in rows]) if can_view_whatsapp and rows else ([] if can_view_whatsapp else None)
    return {'items':items,'total':total,'limit':limit,'offset':offset,
            'stats':await stats(db,tenant_id,filters),'whatsapp':summary}
