import { LinkDomain, LinkSubDomain, LinkServiceName } from '../../config/constants';

/**
 * Builds the X-API-* headers required by Link Unified Gateway
 *
 * Every Link API call requires exactly 3 custom headers:
 *   X-API-Domain     → 'payment' | 'merchant'
 *   X-API-SubDomain  → operation-specific (e.g. 'pos.wallets.payments')
 *   X-API-ServiceName → action (e.g. 'initiate', 'confirm', 'get')
 */
export interface LinkHeaders {
  'X-API-Domain': string;
  'X-API-SubDomain': string;
  'X-API-ServiceName': string;
  Authorization?: string;
}

export function buildLinkHeaders(
  domain: LinkDomain,
  subDomain: LinkSubDomain | string,
  serviceName: LinkServiceName,
  accessToken?: string,
): LinkHeaders {
  const headers: LinkHeaders = {
    'X-API-Domain': domain,
    'X-API-SubDomain': subDomain,
    'X-API-ServiceName': serviceName,
  };

  if (accessToken) {
    headers.Authorization = `Bearer ${accessToken}`;
  }

  return headers;
}

// ── Pre-built header configs for common operations ──

export const HEADERS = {
  // Payment Operations
  initiatePayment: () =>
    buildLinkHeaders(LinkDomain.PAYMENT, LinkSubDomain.POS_WALLETS_PAYMENTS, LinkServiceName.INITIATE),

  confirmPayment: () =>
    buildLinkHeaders(LinkDomain.PAYMENT, LinkSubDomain.POS_WALLETS_PAYMENTS, LinkServiceName.CONFIRM),

  issueVoucher: () =>
    buildLinkHeaders(LinkDomain.PAYMENT, LinkSubDomain.POS_WALLETS_VOUCHERS, LinkServiceName.ISSUE),

  captureVoucher: () =>
    buildLinkHeaders(LinkDomain.PAYMENT, LinkSubDomain.POS_WALLETS_VOUCHERS, LinkServiceName.CAPTURE),

  // Fees
  getFees: () =>
    buildLinkHeaders(LinkDomain.PAYMENT, LinkSubDomain.FEES, LinkServiceName.GET),

  // Transaction Queries
  getTransactionRequest: () =>
    buildLinkHeaders(LinkDomain.PAYMENT, LinkSubDomain.REQUESTS, LinkServiceName.GET),

  getAllTransactionRequests: () =>
    buildLinkHeaders(LinkDomain.PAYMENT, LinkSubDomain.REQUESTS, LinkServiceName.ALL),

  getPaymentStatus: () =>
    buildLinkHeaders(LinkDomain.PAYMENT, LinkSubDomain.REQUESTS, LinkServiceName.STATUS),

  getTransaction: () =>
    buildLinkHeaders(LinkDomain.PAYMENT, LinkSubDomain.TRANSACTIONS, LinkServiceName.GET),

  getTransactionStatus: () =>
    buildLinkHeaders(LinkDomain.PAYMENT, LinkSubDomain.TRANSACTIONS, LinkServiceName.STATUS),

  getAllTransactions: () =>
    buildLinkHeaders(LinkDomain.PAYMENT, LinkSubDomain.TRANSACTIONS, LinkServiceName.ALL),

  // Lookup
  getCompanies: () =>
    buildLinkHeaders(LinkDomain.PAYMENT, LinkSubDomain.COMPANIES, LinkServiceName.GET),

  getCurrencies: () =>
    buildLinkHeaders(LinkDomain.PAYMENT, LinkSubDomain.CURRENCIES, LinkServiceName.GET),

  getCountries: () =>
    buildLinkHeaders(LinkDomain.PAYMENT, LinkSubDomain.COUNTRIES, LinkServiceName.GET),

  getProvinces: () =>
    buildLinkHeaders(LinkDomain.PAYMENT, LinkSubDomain.PROVINCES, LinkServiceName.GET),

  getRegions: () =>
    buildLinkHeaders(LinkDomain.PAYMENT, LinkSubDomain.REGIONS, LinkServiceName.GET),

  getMethods: () =>
    buildLinkHeaders(LinkDomain.PAYMENT, LinkSubDomain.METHODS, LinkServiceName.GET),

  getInstruments: () =>
    buildLinkHeaders(LinkDomain.PAYMENT, LinkSubDomain.INSTRUMENTS, LinkServiceName.GET),

  getServices: () =>
    buildLinkHeaders(LinkDomain.PAYMENT, LinkSubDomain.SERVICES, LinkServiceName.GET),

  // Merchant
  getMerchantAccounts: () =>
    buildLinkHeaders(LinkDomain.MERCHANT, LinkSubDomain.ACCOUNTS, LinkServiceName.GET),

  getMerchantConnections: () =>
    buildLinkHeaders(LinkDomain.MERCHANT, LinkSubDomain.CONNECTIONS, LinkServiceName.GET),
} as const;
