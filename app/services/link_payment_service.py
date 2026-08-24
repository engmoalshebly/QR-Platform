"""
Link Payment Service — HTTP client for the Link Gateway microservice.

This service communicates with the NestJS link-gateway-service running
at LINK_GATEWAY_URL to process wallet-based payments (OTP flow).
"""
import logging
import httpx
from typing import Optional, Dict, Any, List
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class LinkPaymentError(Exception):
    """Raised when a Link Gateway API call fails."""
    def __init__(self, message: str, status_code: int = 0, response_data: Optional[dict] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data or {}


class LinkPaymentService:
    """HTTP client for the internal Link Gateway Service (NestJS)."""

    def __init__(self):
        self.base_url = settings.link_gateway_url.rstrip("/")
        self.api_key = settings.link_gateway_api_key
        self.timeout = getattr(settings, 'external_timeout_seconds', 30.0)

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key,
        }

    def is_configured(self) -> bool:
        """Check if Link Gateway is properly configured."""
        return bool(self.base_url and self.api_key and self.api_key != "your-internal-api-key")

    # ──────────────────────────────────────────
    # Providers (Wallets)
    # ──────────────────────────────────────────

    async def get_providers(self) -> List[Dict[str, Any]]:
        """Fetch available payment providers (wallets) from Link Gateway."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.get(
                    f"{self.base_url}/api/v1/payments/providers",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("providers", [])
            except httpx.HTTPStatusError as e:
                logger.error("Link Gateway providers error: %s %s", e.response.status_code, e.response.text[:200])
                raise LinkPaymentError(
                    f"Failed to fetch providers: {e.response.status_code}",
                    status_code=e.response.status_code,
                )
            except httpx.RequestError as e:
                logger.error("Link Gateway connection error: %s", str(e))
                raise LinkPaymentError(f"Connection error: {str(e)}")

    # ──────────────────────────────────────────
    # Fees
    # ──────────────────────────────────────────

    async def calculate_fees(
        self,
        provider_code: str,
        amount: float,
        currency: str = "YER",
    ) -> Dict[str, Any]:
        """Calculate payment fees before initiating."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(
                    f"{self.base_url}/api/v1/payments/fees",
                    headers=self._headers(),
                    json={
                        "providerCode": provider_code,
                        "amount": amount,
                        "currency": currency,
                    },
                )
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                logger.error("Link Gateway fees error: %s", e.response.text[:200])
                raise LinkPaymentError(
                    f"Failed to calculate fees: {e.response.status_code}",
                    status_code=e.response.status_code,
                )
            except httpx.RequestError as e:
                raise LinkPaymentError(f"Connection error: {str(e)}")

    # ──────────────────────────────────────────
    # Payment Lifecycle
    # ──────────────────────────────────────────

    async def initiate_payment(
        self,
        order_id: str,
        app_id: str,
        provider_code: str,
        wallet_number: str,
        amount: float,
        currency: str = "YER",
        metadata: Optional[dict] = None,
    ) -> Dict[str, Any]:
        """
        Initiate a payment via Link Gateway (Step 1 of OTP flow).

        Returns:
            {
                "success": true,
                "paymentId": "uuid",
                "status": "OTP_REQUIRED",
                "fees": 40,
                "commission": 0,
                "totalAmount": 2040,
                "expiresAt": "2026-08-20T13:15:00.000Z"
            }
        """
        payload = {
            "orderId": order_id,
            "appId": app_id,
            "paymentMethod": "WALLET_OTP",
            "providerCode": provider_code,
            "walletNumber": wallet_number,
            "amount": amount,
            "currency": currency,
        }
        if metadata:
            payload["metadata"] = metadata

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(
                    f"{self.base_url}/api/v1/payments",
                    headers=self._headers(),
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                if not data.get("success"):
                    raise LinkPaymentError(
                        data.get("message", "Payment initiation failed"),
                        response_data=data,
                    )
                return data
            except httpx.HTTPStatusError as e:
                error_detail = e.response.text[:300]
                logger.error("Link Gateway initiate error: %s %s", e.response.status_code, error_detail)
                raise LinkPaymentError(
                    f"Payment initiation failed: {error_detail}",
                    status_code=e.response.status_code,
                )
            except httpx.RequestError as e:
                raise LinkPaymentError(f"Connection error: {str(e)}")

    async def confirm_payment(
        self,
        payment_id: str,
        otp: str,
    ) -> Dict[str, Any]:
        """
        Confirm a payment with OTP (Step 2 of OTP flow).

        Returns:
            {
                "success": true,
                "paymentId": "uuid",
                "status": "SUCCESS",
                "transactionId": "87839846537",
                "amount": 2000,
                "paidAt": "2026-08-20T10:16:30.000Z"
            }
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(
                    f"{self.base_url}/api/v1/payments/{payment_id}/confirm",
                    headers=self._headers(),
                    json={"otp": otp},
                )
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                error_detail = e.response.text[:300]
                logger.error("Link Gateway confirm error: %s %s", e.response.status_code, error_detail)
                raise LinkPaymentError(
                    f"Payment confirmation failed: {error_detail}",
                    status_code=e.response.status_code,
                )
            except httpx.RequestError as e:
                raise LinkPaymentError(f"Connection error: {str(e)}")

    async def get_payment_status(self, payment_id: str) -> Dict[str, Any]:
        """Get payment details and current status."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.get(
                    f"{self.base_url}/api/v1/payments/{payment_id}",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                raise LinkPaymentError(
                    f"Failed to get payment: {e.response.status_code}",
                    status_code=e.response.status_code,
                )
            except httpx.RequestError as e:
                raise LinkPaymentError(f"Connection error: {str(e)}")

    async def health_check(self) -> bool:
        """Check if Link Gateway Service is healthy."""
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                resp = await client.get(f"{self.base_url}/health")
                return resp.status_code == 200
            except Exception:
                return False


# ── Singleton ──
_link_service: Optional[LinkPaymentService] = None


def get_link_payment_service() -> LinkPaymentService:
    """Get or create the Link Payment service singleton."""
    global _link_service
    if _link_service is None:
        _link_service = LinkPaymentService()
    return _link_service
