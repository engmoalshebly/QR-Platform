from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache
import ipaddress
from urllib.parse import urlparse


def _is_private_db_host(host: str) -> bool:
    """True for a bare service name (no dots), localhost, or a private/loopback IP."""
    if not host:
        return False
    if host == "localhost" or "." not in host and ":" not in host:
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback


class Settings(BaseSettings):
    # Supabase
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_key: str = ""  # alias for supabase_anon_key
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""
    supabase_jwt_issuer: str = ""

    # Database
    database_url: str = ""
    database_app_url: str = ""  # non-superuser connection for RLS enforcement
    # "verify" (default): TLS with full certificate verification, required for a
    # remote/managed database.  "disable": plain connection, accepted in
    # production only when the database is on a private network (a bare compose
    # service name, loopback or RFC1918 address) -- see validate_for_production.
    database_ssl: str = "verify"

    # Link Gateway (local wallet payments — YER)
    link_gateway_url: str = "http://localhost:3000"
    link_gateway_api_key: str = ""

    # OpenWA: operator-configured internal endpoint, never supplied by tenants.
    openwa_enabled: bool = False
    openwa_base_url: str = ""
    openwa_master_key: str = ""
    whatsapp_encryption_key: str = ""
    whatsapp_dispatch_interval_seconds: int = 5

    # SMTP
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_admin_email: str = ""
    smtp_sender_name: str = "Qr Platform"

    # App
    app_url: str = "http://localhost:9000"
    app_env: str = "development"
    cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    db_echo: bool = False
    external_timeout_seconds: float = 10.0
    external_retry_attempts: int = 3
    # How long a request may wait for another request's monthly-usage reservation
    # lock before it is answered with USAGE_BUSY (HTTP 409).
    usage_lock_wait_seconds: int = 8
    # When a paid plan has ended and was not renewed, tenant-scoped writes are
    # refused (read-only workspace) until staff activate a renewal.  The renewal
    # request itself, notifications and the profile stay available.
    expired_read_only: bool = True
    # Also keep gate scanning/sync working while read-only.  Off by default: the
    # product decision is "everything is view-only until renewal".
    expired_allow_checkin: bool = False
    scheduler_interval_seconds: int = 3600
    run_embedded_scheduler: bool = False

    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.1

    content_security_policy: str = ""
    trusted_proxy_ips: str = ""
    metrics_access_token: str = ""
    metrics_max_series: int = 500
    password_min_length: int = 12
    otp_hmac_secret: str = ""
    org_request_encryption_key: str = ""
    org_request_upload_max_bytes: int = 5 * 1024 * 1024
    platform_admin_require_aal2: bool = False
    platform_superadmin_emails: str = ""

    # Worker (Celery + Redis)
    redis_url: str = "redis://localhost:6379/0"
    use_worker: bool = True  # False = fallback to BackgroundTask (dev only)

    # Storage
    storage_bucket: str = "invitations"  # Supabase Storage bucket name
    signed_url_expiry: int = 3600  # default signed URL expiry in seconds
    # Admission is staged independently from the durable worker (P2).
    generation_operations_enabled: bool = False
    generation_worker_enabled: bool = False
    generation_workspace_dir: str = "/var/lib/qentry/generation"
    generation_workspace_job_bytes: int = Field(256*1024*1024, ge=32*1024*1024, le=1024*1024*1024)
    generation_workspace_max_bytes: int = Field(2*1024*1024*1024, ge=32*1024*1024)
    generation_export_max_bytes: int = Field(32*1024*1024, ge=1024*1024, le=128*1024*1024)
    generation_export_max_pages: int = Field(50, ge=1, le=250)
    generation_operation_max_cards: int = Field(1000, ge=1, le=10000)
    generation_queue_max_operations: int = Field(1000, ge=1)
    generation_queue_max_cards: int = Field(100000, ge=1)
    generation_tenant_max_operations: int = Field(10, ge=1)
    generation_batch_cards: int = Field(250, ge=1, le=1000)
    # Re-publications of a never-claimed batch before it is failed as DISPATCH_STALLED.
    # Published-but-unfinished batches allowed in the broker at once (keeps FIFO from starving tenants).
    generation_dispatch_window: int = Field(3, ge=1, le=100)
    generation_cleanup_interval_seconds: int = Field(120, ge=10, le=3600)
    generation_republish_max: int = Field(20, ge=3, le=200)

    download_url_expiry: int = 86400 * 7  # batch download URL expiry (7 days)

    # Key rotation policy
    hmac_rotation_days: int = 90  # rotate INVITE_HMAC_SECRET every N days

    # Invitation Security (dedicated HMAC key, NOT reusing JWT secret)
    invite_hmac_secret: str = ""  # Primary signing key for barcodes
    invite_hmac_secret_prev: str = ""  # Previous key for rotation grace period

    @property
    def resolved_hmac_key(self) -> str:
        """Return the dedicated HMAC key used to sign invitation barcodes."""
        if self.invite_hmac_secret:
            return self.invite_hmac_secret
        if self.app_env.lower() == "production":
            raise ValueError("INVITE_HMAC_SECRET is required in production")
        return self.supabase_jwt_secret or "dev-only-change-me"

    @property
    def resolved_anon_key(self) -> str:
        """Return supabase_anon_key, falling back to supabase_key."""
        return self.supabase_anon_key or self.supabase_key

    @property
    def resolved_jwt_issuer(self) -> str:
        """Use an explicit issuer when supplied, otherwise Supabase's issuer."""
        if self.supabase_jwt_issuer:
            return self.supabase_jwt_issuer.rstrip("/")
        return f"{self.supabase_url.rstrip('/')}/auth/v1" if self.supabase_url else ""

    @property
    def resolved_otp_hmac_secret(self) -> str:
        if self.otp_hmac_secret:
            return self.otp_hmac_secret
        if self.is_production:
            raise ValueError("OTP_HMAC_SECRET is required in production")
        return self.supabase_jwt_secret or "dev-only-otp-secret-change-me"

    @property
    def platform_superadmin_email_set(self) -> frozenset[str]:
        return frozenset(
            email.strip().lower()
            for email in self.platform_superadmin_emails.split(",")
            if email.strip()
        )

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    def validate_for_production(self) -> list[str]:
        """Return a list of fatal misconfigurations for a production deployment.

        Empty list means the configuration is safe to boot.
        """
        problems: list[str] = []

        if not self.is_production:
            return problems

        if self.generation_operations_enabled and not self.generation_worker_enabled:
            problems.append("GENERATION_OPERATIONS_ENABLED requires GENERATION_WORKER_ENABLED in production.")

        if not self.invite_hmac_secret:
            problems.append("INVITE_HMAC_SECRET is required in production (barcode signing key).")
        if not self.supabase_url:
            problems.append("SUPABASE_URL is required in production.")
        else:
            parsed_supabase = urlparse(self.supabase_url)
            if (
                parsed_supabase.scheme != "https"
                or not parsed_supabase.hostname
                or parsed_supabase.username
                or parsed_supabase.password
                or parsed_supabase.query
                or parsed_supabase.fragment
            ):
                problems.append("SUPABASE_URL must be a valid HTTPS URL in production.")
        if not self.supabase_jwt_secret and not self.supabase_url:
            problems.append("SUPABASE_JWT_SECRET or SUPABASE_URL must be set to verify tokens.")
        if not self.resolved_anon_key:
            problems.append("SUPABASE_ANON_KEY is required for sign-up and sign-in.")
        if not self.database_url:
            problems.append("DATABASE_URL is required.")
        if not self.supabase_service_role_key:
            problems.append("SUPABASE_SERVICE_ROLE_KEY is required for admin operations.")
        if not self.otp_hmac_secret:
            problems.append("OTP_HMAC_SECRET is required for password-reset secrets.")
        if not self.org_request_encryption_key:
            problems.append("ORG_REQUEST_ENCRYPTION_KEY is required for pending organization requests.")
        if not self.metrics_access_token:
            problems.append("METRICS_ACCESS_TOKEN is required to protect /metrics.")
        if not self.platform_admin_require_aal2:
            problems.append("PLATFORM_ADMIN_REQUIRE_AAL2 must be enabled in production.")
        if not self.platform_superadmin_email_set:
            problems.append("PLATFORM_SUPERADMIN_EMAILS is required for staff management break-glass access.")
        if not self.database_app_url:
            problems.append(
                "DATABASE_APP_URL should be set to a non-superuser connection "
                "(qentry_app role) for RLS enforcement. Apply migration_v52 first."
            )
        ssl_mode = self.database_ssl.strip().lower()
        if ssl_mode not in {"verify", "disable"}:
            problems.append("DATABASE_SSL must be 'verify' or 'disable'.")
        elif ssl_mode == "disable":
            for name, url in (("DATABASE_URL", self.database_url), ("DATABASE_APP_URL", self.database_app_url)):
                host = urlparse(url.replace("postgresql+asyncpg://", "postgresql://")).hostname or ""
                if not _is_private_db_host(host):
                    problems.append(
                        f"DATABASE_SSL=disable is only allowed for a private-network database; "
                        f"{name} host '{host}' is not."
                    )
        if not self.redis_url:
            problems.append("REDIS_URL is required in production for distributed rate limiting.")
        if not self.smtp_host or not self.smtp_user or not self.smtp_pass:
            problems.append("SMTP_HOST, SMTP_USER, and SMTP_PASS are required for transactional email.")
        # LINK_GATEWAY_API_KEY is deliberately not required: online payments are
        # disabled and subscriptions are approved manually (RUNBOOK section 6a).
        # LinkPaymentService.is_configured() fails closed when the key is empty.
        origins = [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]
        if not origins:
            problems.append("CORS_ALLOWED_ORIGINS must be set in production.")
        if "*" in origins:
            problems.append("CORS_ALLOWED_ORIGINS must not be '*' when credentials are allowed.")
        if any("localhost" in o or "127.0.0.1" in o for o in origins):
            problems.append("CORS_ALLOWED_ORIGINS contains localhost in production.")
        for origin in origins:
            parsed_origin = urlparse(origin)
            if (
                parsed_origin.scheme != "https"
                or not parsed_origin.hostname
                or parsed_origin.path
                or parsed_origin.username
                or parsed_origin.password
                or parsed_origin.params
                or parsed_origin.query
                or parsed_origin.fragment
            ):
                problems.append(f"CORS_ALLOWED_ORIGINS contains an invalid production origin: {origin}")
        parsed_app_url = urlparse(self.app_url)
        if (
            parsed_app_url.scheme != "https"
            or not parsed_app_url.hostname
            or parsed_app_url.username
            or parsed_app_url.password
            or parsed_app_url.query
            or parsed_app_url.fragment
        ):
            problems.append("APP_URL must be a valid HTTPS URL in production.")
        if self.password_min_length < 12:
            problems.append("PASSWORD_MIN_LENGTH must be at least 12 in production.")
        for setting_name, secret in (
            ("INVITE_HMAC_SECRET", self.invite_hmac_secret),
            ("OTP_HMAC_SECRET", self.otp_hmac_secret),
            ("ORG_REQUEST_ENCRYPTION_KEY", self.org_request_encryption_key),
            ("METRICS_ACCESS_TOKEN", self.metrics_access_token),
        ):
            if secret and len(secret.encode("utf-8")) < 32:
                problems.append(f"{setting_name} must be at least 32 bytes long.")
        if self.org_request_upload_max_bytes <= 0 or self.org_request_upload_max_bytes > 10 * 1024 * 1024:
            problems.append("ORG_REQUEST_UPLOAD_MAX_BYTES must be between 1 byte and 10MB.")
        for proxy in (value.strip() for value in self.trusted_proxy_ips.split(",") if value.strip()):
            try:
                ipaddress.ip_network(proxy, strict=False)
            except ValueError:
                problems.append(f"TRUSTED_PROXY_IPS contains an invalid address or CIDR: {proxy}")

        if self.openwa_enabled:
            endpoint = urlparse(self.openwa_base_url)
            if endpoint.scheme not in ('http', 'https') or not endpoint.hostname or endpoint.username is not None or endpoint.password is not None or endpoint.query or endpoint.fragment:
                problems.append("OPENWA_BASE_URL must be a fixed HTTP(S) endpoint without credentials or query.")
            elif endpoint.scheme == 'http' and not _is_private_db_host(endpoint.hostname):
                problems.append("OPENWA_BASE_URL must use HTTPS outside the private service network.")
            if len(self.openwa_master_key) < 32:
                problems.append("OPENWA_MASTER_KEY must be at least 32 characters when OpenWA is enabled.")
            if len(self.whatsapp_encryption_key) < 32:
                problems.append("WHATSAPP_ENCRYPTION_KEY must be at least 32 characters when OpenWA is enabled.")
        return problems

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
