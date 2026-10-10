"""Guard against ``:name::type`` immediately after a bind parameter in raw SQL.

SQLAlchemy's text() scans the SQL string for ``:name`` tokens itself; ``::`` is
PostgreSQL's cast operator, not part of bind-parameter syntax, and the two
constructs do not mix reliably: in several real statements in this codebase,
`:name::type` right after each other was left as literal, unbound text in the
compiled SQL, so PostgreSQL itself raised a syntax error on every call -- a
100% reproducible bug that no test caught because nothing had exercised those
exact endpoints over real HTTP before (verified directly: see migration-less
fixes to app/routes/{subscriptions,guests,tenants,digital_invitations}.py in
this change). ``CAST(:name AS type)`` is unambiguous and is the convention
already used elsewhere in this codebase (app/services/notification_service.py).

This is a static, no-database check: it is cheap, runs everywhere, and catches
the mistake before it ever reaches a real request.
"""
import re
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "app"

# A bind param name immediately followed by a PostgreSQL cast: :name::type
BAD_PATTERN = re.compile(r":[a-zA-Z_][a-zA-Z0-9_]*::[a-zA-Z_]+(\[\])?")

PY_FILES = sorted(p for p in APP_DIR.rglob("*.py") if "__pycache__" not in p.parts)


def test_inventory_is_non_empty():
    assert len(PY_FILES) > 50, f"only found {len(PY_FILES)} files under app/ — path probably wrong"


@pytest.mark.parametrize("path", PY_FILES, ids=lambda p: str(p.relative_to(APP_DIR.parent)))
def test_no_bind_param_immediately_cast_in_sql(path: Path):
    source = path.read_text(encoding="utf-8")
    matches = [m.group(0) for m in BAD_PATTERN.finditer(source)]
    assert not matches, (
        f"{path.relative_to(APP_DIR.parent)} uses {matches} — SQLAlchemy may not bind the "
        "parameter before PostgreSQL sees the '::' cast. Use CAST(:name AS type) instead."
    )
