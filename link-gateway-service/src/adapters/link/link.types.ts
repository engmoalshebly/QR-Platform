// ============================================
// Link API Type Definitions
// ============================================

/** Standard Link API response wrapper */
export interface LinkResponse<T = unknown> {
  success: boolean;
  responseCode: string;
  message?: string;
  entity?: T;
  entities?: T[];
}

/** Authentication response */
export interface LinkAuthToken {
  access_token: string;
  expires_in: number;
  token_type: string;
}

/** Company from Lookup */
export interface LinkCompany {
  code: string;
  name: string;
  nameEn?: string;
  isActive: boolean;
  imageUrl?: string;
  logoUrl?: string;
  businessType?: number;
  sectorType: number | string;
}

/** Currency from Lookup */
export interface LinkCurrency {
  code: string;
  name: string;
  nameEn: string;
  isActive: boolean;
}

/** Service from Lookup */
export interface LinkService {
  code: string;
  name: string;
  nameEn: string;
  isActive: boolean;
}

/** Instrument from Lookup */
export interface LinkInstrument {
  code: string;
  name: string;
  nameEn: string;
}

/** Fees response */
export interface LinkFeesResponse {
  chargesAmount: number;
  chargesCurrencyCode: string;
  fees: number;
  feesCurrencyCode: string;
  commission: number;
  commissionCurrencyCode: string;
  details: {
    sourceFees: number;
    switchFees: number;
    gwFees: number;
    beneficiaryFees: number;
  };
}

/** Account party (source or beneficiary) */
export interface LinkAccountParty {
  organizationCode: string;
  accountType: string;
  accountId: string;
  subAccountId?: string;
  subId?: string;
}

/** KYC data */
export interface LinkKYC {
  firstName?: string;
  secondName?: string;
  thirdName?: string;
  familyName?: string;
  mobileNumber?: string;
  fullName?: string;
  idType?: string;
  idNumber?: string;
  IdNumber?: string;
  IdType?: string;
  gendar?: string;
}

/** Metadata key-value pair */
export interface LinkMetaData {
  key: string;
  value: string;
}

/** Initiate payment request body */
export interface LinkInitiateRequest {
  requestId: string;
  referenceNumber: string;
  currencyCode: string;
  amount: number;
  amountType: number;
  tokenNumber?: string;
  captureMode: 'MANUAL' | 'AUTO';
  isBeneficiaryInitiated: boolean;
  source: LinkAccountParty;
  beneficiary: LinkAccountParty;
  senderKYC: LinkKYC;
  receiverKYC: LinkKYC;
  notes?: string;
  expireDate?: string;
  termenal?: {
    id?: string;
    terminalAlias?: string;
    country?: string;
    city?: string;
    region?: string;
    channel?: string;
    terminalName?: string;
  };
  metaData?: LinkMetaData[];
}

/** Initiate payment response entity */
export interface LinkInitiateResponse {
  requestId: string;
  referenceNumber: string;
  expiryDate: string;
  beneficiary: LinkAccountParty;
  source: LinkAccountParty;
  senderKYC: LinkKYC;
  receiverKYC: LinkKYC;
  reSourceToken: string;
  unifiedToken: string;
  fees: number;
  feesCurrency?: string;
  commission: number;
  commissionCurrency?: string;
  currencyCode: string;
  amount: number;
  transactionDate?: string;
  metaData?: LinkMetaData[];
}

/** Confirm payment request body */
export interface LinkConfirmRequest {
  requestId: string;
  referenceNumber: string;
  currencyCode: string;
  amount: number;
  organizationCode: string;
  autherizationType: 'Token' | 'OTP';
  autherizationId: string;
  oneTimeCode: string;
  metaData?: LinkMetaData[];
}

/** Confirm payment response entity */
export interface LinkConfirmResponse {
  currencyCode: string;
  amount: number;
  balance?: number;
  transactionStatus: number | string;
  transactionId: string;
  settlementDate?: string;
  transactionDate?: string;
  providerReference?: string;
}

/** Transaction request entity (query/status) */
export interface LinkTransactionRequest {
  requestDate: string;
  sourceReference: string;
  currency: string;
  isBeneficiaryInitiated: boolean;
  requestId: string;
  expiryDate: string;
  beneficiary: LinkAccountParty;
  source: LinkAccountParty;
  senderKYC: LinkKYC;
  receiverKYC: LinkKYC;
  reSourceToken: string;
  fees: number;
  commission: number;
  amount: number;
  transactionId: string;
  status?: string;
  confirmationId?: string;
}

/** Transaction entity (from /v1/transactions) */
export interface LinkTransaction {
  transactionTime: string;
  currency: string;
  serviceId?: string;
  sourceReference: string;
  requestTime: string;
  details?: string;
  transactionStatus: string;
  clientId?: string;
  sender?: string;
  receiver?: string;
  fees: number;
  requestId: string;
  feesCurrency: string;
  commission: number;
  commissionCurrency: string;
  amount: number;
  transactionId: string;
}

/** Balance entity */
export interface LinkBalance {
  currencyCode: string;
  withdrawalAvailableBalance: number;
  withdrawalOnHold: number;
  depositAvailableBalance: number;
  depositOnHold: number;
  balance: number;
}

/** Connection entity */
export interface LinkConnection {
  code: string;
  isActive: boolean;
  metaData?: LinkMetaData[];
}
