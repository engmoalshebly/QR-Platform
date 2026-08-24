import { randomUUID } from 'node:crypto';

/**
 * Generate a unique UUID v4 for requestId
 */
export function generateRequestId(): string {
  return randomUUID();
}

/**
 * Generate a numeric reference number (11 digits)
 * Format: timestamp-based to ensure uniqueness
 */
export function generateReferenceNumber(): string {
  const now = Date.now();
  const random = Math.floor(Math.random() * 100);
  return `${now}${random}`.slice(-11);
}

/**
 * Mask sensitive data for logging/storage
 * "773391212" → "773***212"
 */
export function maskAccountId(accountId: string): string {
  if (!accountId || accountId.length < 6) return '***';
  return `${accountId.slice(0, 3)}***${accountId.slice(-3)}`;
}

/**
 * Mask a token for safe storage
 * "8D8D29BF04BA58AC..." → "8D8D***93F6"
 */
export function maskToken(token: string): string {
  if (!token || token.length < 8) return '***';
  return `${token.slice(0, 4)}***${token.slice(-4)}`;
}

/**
 * Deep mask sensitive fields in a payload before storage
 */
export function maskPayload(payload: unknown): unknown {
  if (!payload || typeof payload !== 'object') return payload;

  const sensitiveKeys = [
    'access_token', 'client_secret', 'password',
    'oneTimeCode', 'otp', 'idNumber', 'IdNumber',
  ];

  const masked = { ...(payload as Record<string, unknown>) };

  for (const key of Object.keys(masked)) {
    if (sensitiveKeys.includes(key)) {
      masked[key] = '***MASKED***';
    } else if (key === 'accountId' && typeof masked[key] === 'string') {
      masked[key] = maskAccountId(masked[key] as string);
    } else if (typeof masked[key] === 'object' && masked[key] !== null) {
      masked[key] = maskPayload(masked[key]);
    }
  }

  return masked;
}

/**
 * Check if a Link API response indicates true financial success
 * Must validate all 4 conditions
 */
export function isFinancialSuccess(response: {
  httpStatus: number;
  success?: boolean;
  responseCode?: string;
  transactionStatus?: string | number;
}): boolean {
  const isCodeSuccess = response.responseCode === '2000' || response.responseCode === '0000' || response.responseCode === 'SUCCESS';
  const isStatusSuccess = response.transactionStatus === 1 || response.transactionStatus === '1' || response.transactionStatus === 'Success' || response.transactionStatus === 'Completed';
  return (
    response.httpStatus === 200 &&
    response.success === true &&
    isCodeSuccess &&
    isStatusSuccess
  );
}

/**
 * Check if transaction is pending (not yet confirmed by provider)
 */
export function isTransactionPending(transactionStatus: string | number): boolean {
  return transactionStatus === 3 || transactionStatus === '3' || transactionStatus === 'Pending';
}

/**
 * Sleep for a specified duration (for retry backoff)
 */
export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
