// ============================================
// System Constants
// ============================================

/** Payment statuses managed by our State Machine */
export enum PaymentStatus {
  CREATED = 'CREATED',
  INITIATING = 'INITIATING',
  OTP_REQUIRED = 'OTP_REQUIRED',
  CONFIRMING = 'CONFIRMING',
  SUCCESS = 'SUCCESS',
  FAILED = 'FAILED',
  PENDING = 'PENDING',
  CHECKING = 'CHECKING',
  EXPIRED = 'EXPIRED',
  CANCELLED = 'CANCELLED',
  UNKNOWN = 'UNKNOWN',
}

/** Payment methods supported */
export enum PaymentMethod {
  WALLET_OTP = 'WALLET_OTP',
  PAYMENT_CODE = 'PAYMENT_CODE',
  BANK_TRANSFER = 'BANK_TRANSFER',
}

/** Gateway transaction operation types */
export enum OperationType {
  INITIATE = 'INITIATE',
  CONFIRM = 'CONFIRM',
  STATUS_CHECK = 'STATUS_CHECK',
  FEES = 'FEES',
  VOUCHER_ISSUE = 'VOUCHER_ISSUE',
  VOUCHER_CAPTURE = 'VOUCHER_CAPTURE',
}

/** Link API response codes */
export enum LinkResponseCode {
  SUCCESS = '2000',
}

/** Link transaction status values */
export enum LinkTransactionStatus {
  SUCCESS = '1',
  FAILED = '2',
  PENDING = '3',
}

/** Link X-API-Domain values */
export enum LinkDomain {
  PAYMENT = 'payment',
  MERCHANT = 'merchant',
}

/** Link X-API-SubDomain values */
export enum LinkSubDomain {
  // Payment operations
  POS_WALLETS_PAYMENTS = 'pos.wallets.payments',
  POS_WALLETS_VOUCHERS = 'pos.wallets.vouchers',
  FEES = 'fees',
  REQUESTS = 'requests',
  TRANSACTIONS = 'transactions',

  // Lookup
  COMPANIES = 'companies',
  CURRENCIES = 'Currencies',
  COUNTRIES = 'countries',
  PROVINCES = 'provinces',
  REGIONS = 'regions',
  METHODS = 'methods',
  INSTRUMENTS = 'instruments',
  SERVICES = 'services',
  METHODS_INSTRUMENTS = 'Methodsinstruments',

  // Merchant
  ACCOUNTS = 'accounts',
  CONNECTIONS = 'connections',
}

/** Link X-API-ServiceName values */
export enum LinkServiceName {
  GET = 'get',
  ALL = 'all',
  STATUS = 'status',
  INITIATE = 'initiate',
  CONFIRM = 'confirm',
  ISSUE = 'issue',
  CAPTURE = 'capture',
}

/** Redis key prefixes */
export const REDIS_KEYS = {
  ACCESS_TOKEN: 'link:access_token',
  TOKEN_EXPIRES_AT: 'link:token_expires_at',
  LOOKUP_PREFIX: 'link:lookup:',
} as const;

/** Lookup cache TTL in seconds (6 hours) */
export const LOOKUP_CACHE_TTL = 6 * 60 * 60;

/** Max status check retries for pending payments */
export const MAX_STATUS_CHECK_RETRIES = 10;

/** Status check interval in milliseconds (30 seconds) */
export const STATUS_CHECK_INTERVAL = 30_000;
