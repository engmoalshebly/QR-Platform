#!/usr/bin/env bash
# Read-only production diagnosis. No linking, enabling, sending or retries.
set -euo pipefail
if [ "$#" -ne 1 ]; then
  echo "Usage: $0 TENANT_UUID" >&2
  exit 2
fi
docker exec -i "${QENTRY_API_CONTAINER:-qentry-prod-api-1}" python - "$1" <<'PY'
import asyncio
import json
import sys
from uuid import UUID
from sqlalchemy import text
from app.database import AsyncSessionLocal
from app.services import whatsapp_service as svc

async def main():
    tenant_id = str(UUID(sys.argv[1]))
    # Infrastructure diagnosis explicitly scopes the privileged query. Using
    # AppSessionLocal without tenant context would silently hide rows via RLS.
    async with AsyncSessionLocal() as db:
        conn = (await db.execute(text('''SELECT session_id,status,enabled,
            api_key_ciphertext FROM whatsapp_connections WHERE tenant_id=:tid'''),
            {'tid': tenant_id})).mappings().first()
        result = {'configured': svc.configured(), 'connection_exists': bool(conn)}
        if conn:
            result.update(enabled=conn['enabled'], stored_status=conn['status'])
            if conn['session_id'] and conn['api_key_ciphertext'] and svc.configured():
                try:
                    remote = await svc.provider('GET', 'sessions/' + str(conn['session_id']),
                        key=svc.crypt(conn['api_key_ciphertext'], decrypt=True))
                    result['live_status'] = remote.get('status', 'unknown')
                except svc.ProviderError as exc:
                    result.update(live_status='unavailable', provider_http_status=exc.status)
                except Exception:
                    result['live_status'] = 'credential_or_response_error'
            jobs = (await db.execute(text('''SELECT state,count(*) total
                FROM whatsapp_deliveries WHERE tenant_id=:tid GROUP BY state'''),
                {'tid': tenant_id})).mappings().all()
            result['deliveries'] = {row['state']: row['total'] for row in jobs}
        print(json.dumps(result, ensure_ascii=False))
        return 0 if (result.get('configured') and result.get('enabled')
                     and result.get('live_status') == 'ready') else 1

sys.exit(asyncio.run(main()))
PY
