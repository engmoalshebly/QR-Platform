import { IsString, IsNumber, IsOptional, IsEnum, Min, Length, Matches } from 'class-validator';
import { PaymentMethod } from '../../config/constants';

/** DTO: Create a new payment */
export class CreatePaymentDto {
  @IsString()
  orderId: string; // External order/invoice ID

  @IsString()
  appId: string; // Which app is calling

  @IsEnum(PaymentMethod)
  paymentMethod: PaymentMethod;

  @IsString()
  providerCode: string; // e.g. 'Floosak'

  @IsString()
  walletNumber: string; // Customer's wallet/account number

  @IsNumber()
  @Min(1)
  amount: number;

  @IsOptional()
  @IsString()
  currency?: string; // Default: YER

  @IsOptional()
  metadata?: Record<string, string>;
}

/** DTO: Confirm payment with OTP */
export class ConfirmPaymentDto {
  @IsString()
  @Length(4, 10)
  @Matches(/^\d+$/)
  otp: string; // OTP code from customer's wallet
}

/** DTO: Calculate fees */
export class CalculateFeesDto {
  @IsString()
  providerCode: string;

  @IsNumber()
  @Min(1)
  amount: number;

  @IsOptional()
  @IsString()
  currency?: string;

  @IsOptional()
  @IsString()
  serviceCode?: string;
}

/** Internal payment record shape */
export interface PaymentRecord {
  id: string;
  external_order_id: string;
  external_app_id: string;
  gateway: string;
  payment_method: string;
  provider_code: string;
  amount: number;
  fees: number;
  commission: number;
  total_amount: number;
  currency: string;
  source_org: string;
  source_account_type: string;
  source_account_id: string;
  beneficiary_org: string;
  beneficiary_account_type: string;
  beneficiary_account_id: string;
  status: string;
  failure_reason?: string;
  created_at: string;
  updated_at: string;
  initiated_at?: string;
  confirmed_at?: string;
  paid_at?: string;
  failed_at?: string;
  expired_at?: string;
  metadata?: Record<string, unknown>;
}

/** Internal gateway transaction record shape */
export interface GatewayTransactionRecord {
  id: string;
  payment_id: string;
  gateway: string;
  operation_type: string;
  client_request_id: string;
  client_reference_number: string;
  gateway_request_id?: string;
  gateway_reference_number?: string;
  resource_token?: string;
  unified_token?: string;
  transaction_id?: string;
  provider_reference?: string;
  amount?: number;
  fees?: number;
  commission?: number;
  currency?: string;
  http_status?: number;
  gateway_success?: boolean;
  response_code?: string;
  response_message?: string;
  transaction_status?: string;
  expires_at?: string;
  transaction_at?: string;
  settlement_at?: string;
  last_status_check_at?: string;
  request_payload?: unknown;
  response_payload?: unknown;
  created_at: string;
}
