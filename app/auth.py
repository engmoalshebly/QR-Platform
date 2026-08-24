from typing import Any, Dict, Optional
import asyncio
import logging
import time

import httpx
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwk, jwt, JWTError
from pydantic import BaseModel
from uuid import UUID

from app.config import get_settings

logger = logging.getLogger(__name__)
security = HTTPBearer()
settings = get_settings()

# Supabase access tokens are always issued with this audience.
JWT_AUDIENCE = "authenticated"


class CurrentUser(BaseModel):
    id: UUID
    email: Optional[str] = None
    role: Optional[str] = None  # supabase role (authenticated, service_role)
    aal: Optional[str] = None   # Supabase assurance level (aal1 / aal2)


# ── JWKS cache (keyed by kid, refreshed on a TTL) ──
_JWKS_TTL_SECONDS = 3600
_jwks_cache: Dict[str, Any] = {}
_jwks_fetched_at: float = 0.0
_jwks_lock = asyncio.Lock()


async def get_supabase_jwks(force_refresh: bool = False) -> Dict[str, Any]:
    """Fetch and cache Supabase JWKS for verifying ES256/RS256 tokens.

    Cached in-process for _JWKS_TTL_SECONDS and refreshed on demand when a
    token references an unknown kid (key rotation).
    """
    global _jwks_cache, _jwks_fetched_at
    now = time.monotonic()
    if not force_refresh and _jwks_cache and (now - _jwks_fetched_at) < _JWKS_TTL_SECONDS:
        return _jwks_cache

    async with _jwks_lock:
        now = time.monotonic()
        if not force_refresh and _jwks_cache and (now - _jwks_fetched_at) < _JWKS_TTL_SECONDS:
            return _jwks_cache

        jwks_url = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(jwks_url)
            response.raise_for_status()
            data = response.json()
            keys = {key["kid"]: key for key in data.get("keys", []) if key.get("kid")}
            if not keys:
                raise ValueError("JWKS response contained no usable keys")
            _jwks_cache = keys
            _jwks_fetched_at = now
            return _jwks_cache
        except Exception as exc:
            if _jwks_cache:
                # Serve stale keys rather than hard-failing on a transient outage.
                logger.warning("JWKS refresh failed; serving cached keys error=%s", type(exc).__name__)
                return _jwks_cache
            logger.warning("JWKS refresh failed without cache error=%s", type(exc).__name__)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Identity provider is temporarily unavailable",
            )


async def get_jwk_for_token(token: str) -> Any:
    """Resolve the verification key for a token by its alg/kid.

    Not cached by token (that would grow unbounded and never hit); the
    underlying JWKS is cached by kid in get_supabase_jwks().
    """
    header = jwt.get_unverified_header(token)
    alg = header.get("alg")

    if alg == "HS256":
        # A deployment using asymmetric Supabase signing keys may not have a
        # shared JWT secret at all.  Never let an empty string become a valid
        # HMAC key: python-jose accepts it and would make forged HS256 tokens
        # appear valid.
        if not settings.supabase_jwt_secret:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="HS256 tokens are not configured for this deployment",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return settings.supabase_jwt_secret

    if alg not in {"ES256", "RS256"}:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token signing algorithm",
            headers={"WWW-Authenticate": "Bearer"},
        )

    kid = header.get("kid")
    if not kid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing kid",
            headers={"WWW-Authenticate": "Bearer"},
        )

    jwks = await get_supabase_jwks()
    if kid not in jwks:
        # Possible key rotation — force one refresh before giving up.
        jwks = await get_supabase_jwks(force_refresh=True)
    if kid not in jwks:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: no matching JWK kid found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return jwk.construct(jwks[kid])


async def _decode_verified_token(token: str) -> dict:
    """Verify a Supabase access token with exactly its declared algorithm."""
    algorithm = jwt.get_unverified_header(token).get("alg")
    decode_kwargs: dict[str, Any] = {
        "algorithms": [algorithm],
        "audience": JWT_AUDIENCE,
    }
    if settings.resolved_jwt_issuer:
        decode_kwargs["issuer"] = settings.resolved_jwt_issuer
    return jwt.decode(token, await get_jwk_for_token(token), **decode_kwargs)


async def decode_supabase_jwt(token: str) -> dict:
    """Decode and verify a Supabase JWT token."""
    try:
        return await _decode_verified_token(token)
    except HTTPException:
        raise
    except (JWTError, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> CurrentUser:
    """Extract current user from a verified Supabase JWT (audience enforced)."""
    payload = await decode_supabase_jwt(credentials.credentials)

    if payload.get("role") != "authenticated":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing user ID",
        )

    try:
        return CurrentUser(
            id=UUID(user_id),
            email=payload.get("email"),
            role=payload.get("role"),
            aal=payload.get("aal"),
        )
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_tenant_id_from_header(request: Request) -> UUID:
    """Return the resolved tenant ID for this request.

    Primary source: contextvars (set by TenantResolutionMiddleware after
    validating the tenant exists, is active, and the user is a member).
    Fallback: raw X-Tenant-ID header (for paths that bypass the middleware).

    Using contextvars as the primary source eliminates the risk of a route
    trusting a raw header that the middleware hasn't validated yet.
    """
    from app.tenant_context import get_current_tenant_id

    ctx_tenant = get_current_tenant_id()
    if ctx_tenant:
        return ctx_tenant if isinstance(ctx_tenant, UUID) else UUID(str(ctx_tenant))

    tenant_id = request.headers.get("X-Tenant-ID")
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Tenant-ID header is required",
        )
    try:
        return UUID(tenant_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid X-Tenant-ID format",
        )
