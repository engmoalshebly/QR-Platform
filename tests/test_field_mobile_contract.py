from app.main import app


def test_field_mobile_routes_are_registered():
    # FastAPI >=0.142 keeps included routers nested (_IncludedRouter), so the
    # OpenAPI schema is the reliable flat view of every API path.  Routes hidden
    # from the schema (the /field SPA fallback) are read from app.routes.
    paths = set(app.openapi()["paths"]) | {getattr(route, "path", "") for route in app.routes}
    assert "/api/v1/mobile/checkin-pack/{shift_id}" in paths
    assert "/api/v1/mobile/checkins" in paths
    assert "/api/v1/mobile/checkins/sync" in paths
    assert "/api/v1/mobile/invitations/search" in paths
    assert "/api/v1/mobile/assistance" in paths
    assert "/api/v1/mobile/settings" in paths
    assert "/api/v1/mobile/events" in paths
    assert "/api/v1/mobile/events/{event_id}/briefing" in paths
    assert "/field/{asset_path:path}" in paths


def test_field_scanner_isolation_header_policy():
    import asyncio
    from starlette.requests import Request
    from starlette.responses import Response
    from app.middleware import SecurityHeadersMiddleware

    async def request_for(path: str) -> Response:
        scope = {"type": "http", "method": "GET", "path": path, "headers": [], "scheme": "http", "server": ("test", 80)}
        return await SecurityHeadersMiddleware(app).dispatch(Request(scope), lambda _request: _response())

    async def _response() -> Response:
        return Response("ok")

    field = asyncio.run(request_for("/field/"))
    dashboard = asyncio.run(request_for("/"))
    assert field.headers["Permissions-Policy"] == "camera=(self), microphone=(), geolocation=()"
    assert dashboard.headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"


def test_field_mobile_contract_keeps_raw_code_and_distinct_manual_permission():
    from pathlib import Path

    source = (Path(__file__).parents[1] / "app" / "routes" / "mobile.py").read_text(encoding="utf-8")
    assert "raw_code: Optional[str]" in source
    assert 'require_permission(db, tenant_id, user.id, "checkin.manual")' in source
    assert "_create_assistance_request" in source
    assert "is_available_today" in source
    assert "لا يمكن تشغيل بوابة الحفل قبل يوم الحفل أو بعد انتهائه" in source
