# Qentry — multi-tenant event operations platform

Qentry lets organizations run events (invitations, registration, QR check-in) and
lets organizer teams operate them. Every tenant's data is isolated.

## Components

| Path | What it is |
|---|---|
| `app/` | FastAPI backend: API, tenant resolution, RBAC, billing limits, workers |
| `frontend/` | Management console (React + Vite) |
| `field-pwa/` | Field scanner PWA, served by the API at `/field/` |
| `field-expo/` | Native field app (Expo) |
| `link-gateway-service/` | Payment gateway (NestJS), internal only |
| `supabase/` | Schema and numbered migrations |
| `scripts/` | Migration runner for CI, operations scripts (backup, restore drill) |
| `deploy/` | Production Caddy config, environment templates, runbook |

## Local development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
docker compose up -d postgres redis      # local services; see docker-compose.yml
cp .env.example .env                     # fill the Supabase values
uvicorn app.main:app --reload --port 9000
```

Frontend: `cd frontend && npm ci && npm run dev`.

## Tests

```bash
python scripts/migrations/ci_migrate.py  # blank database only
pytest                                   # full suite (needs PostgreSQL and Redis)
pytest tests/test_cross_tenant_isolation.py tests/test_tenant_status_and_exemptions.py
cd link-gateway-service && npm ci && npm test
```

CI (`.github/workflows/ci.yml`) runs all of the above plus audits, lint, builds,
Dockerfile lint, the image smoke check and secret scanning.

## Production

See [deploy/RUNBOOK.md](deploy/RUNBOOK.md) for topology, release, rollback, secret
rotation, backups, incidents and the go-live gate. Security policy: [SECURITY.md](SECURITY.md).

## License

See [LICENSE](LICENSE).
