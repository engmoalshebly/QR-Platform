import { HttpException, HttpStatus } from '@nestjs/common';

/** Base gateway error */
export class GatewayError extends HttpException {
  constructor(
    public readonly code: string,
    message: string,
    public readonly details?: Record<string, unknown>,
    status: HttpStatus = HttpStatus.BAD_GATEWAY,
  ) {
    super({ success: false, code, message, details }, status);
  }
}

/** Link API returned an error response */
export class LinkApiError extends GatewayError {
  constructor(responseCode: string, message: string, rawResponse?: unknown) {
    super('LINK_API_ERROR', message, {
      responseCode,
      rawResponse,
    });
  }
}

/** Link API unreachable or timed out */
export class LinkConnectionError extends GatewayError {
  constructor(message: string) {
    super('LINK_CONNECTION_ERROR', message, undefined, HttpStatus.SERVICE_UNAVAILABLE);
  }
}

/** Authentication with Link failed */
export class LinkAuthError extends GatewayError {
  constructor(message: string) {
    super('LINK_AUTH_ERROR', message, undefined, HttpStatus.UNAUTHORIZED);
  }
}

/** Payment not found */
export class PaymentNotFoundError extends GatewayError {
  constructor(paymentId: string) {
    super('PAYMENT_NOT_FOUND', `Payment ${paymentId} not found`, undefined, HttpStatus.NOT_FOUND);
  }
}

/** Invalid payment state transition */
export class InvalidStateError extends GatewayError {
  constructor(paymentId: string, currentStatus: string, attemptedAction: string) {
    super(
      'INVALID_STATE',
      `Cannot ${attemptedAction} payment ${paymentId} in status ${currentStatus}`,
      { paymentId, currentStatus, attemptedAction },
      HttpStatus.CONFLICT,
    );
  }
}

/** Payment expired */
export class PaymentExpiredError extends GatewayError {
  constructor(paymentId: string) {
    super('PAYMENT_EXPIRED', `Payment ${paymentId} has expired`, undefined, HttpStatus.GONE);
  }
}
