import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { DatabaseService } from '../../config/database.service';
import { LinkClient } from '../../adapters/link/link.client';
import { HEADERS } from '../../adapters/link/link.headers';
import {
  LinkInitiateRequest,
  LinkInitiateResponse,
  LinkConfirmRequest,
  LinkConfirmResponse,
  LinkTransactionRequest,
} from '../../adapters/link/link.types';
import {
  PaymentStatus,
  OperationType,
} from '../../config/constants';
import {
  validateTransition,
  isTerminalState,
  canConfirm,
} from './payment.state-machine';
import {
  PaymentNotFoundError,
  InvalidStateError,
  PaymentExpiredError,
  LinkApiError,
} from '../../shared/errors';
import {
  generateRequestId,
  generateReferenceNumber,
  maskPayload,
  isFinancialSuccess,
  isTransactionPending,
} from '../../shared/utils';
import { CreatePaymentDto, ConfirmPaymentDto, PaymentRecord, GatewayTransactionRecord } from './payment.types';
import { FeesService } from '../fees/fees.service';

@Injectable()
export class PaymentOrchestrator {
  private readonly logger = new Logger(PaymentOrchestrator.name);

  constructor(
    private readonly db: DatabaseService,
    private readonly linkClient: LinkClient,
    private readonly config: ConfigService,
    private readonly feesService: FeesService,
  ) {}

  // ══════════════════════════════════════════
  // 1. CREATE + INITIATE PAYMENT
  // ══════════════════════════════════════════

  async initiatePayment(dto: CreatePaymentDto) {
    const currency = dto.currency || 'YER';

    // 1. Get fees first
    const feesResult = await this.feesService.getFees(
      dto.providerCode,
      dto.amount,
      currency,
    );

    // 2. Create internal payment record
    const paymentId = generateRequestId();
    const beneficiaryOrg = this.config.get<string>('link.merchant.organizationCode') || 'Link';
    const beneficiaryAccType = this.config.get<string>('link.merchant.accountType') || 'MerchantId';
    const beneficiaryAccId = this.config.get<string>('link.merchant.accountId') || '';

    await this.db.insert<PaymentRecord>('payments', {
      id: paymentId,
      external_order_id: dto.orderId,
      external_app_id: dto.appId,
      gateway: 'LINK',
      payment_method: dto.paymentMethod,
      provider_code: dto.providerCode,
      amount: dto.amount,
      fees: feesResult.fees,
      commission: feesResult.commission,
      total_amount: feesResult.totalAmount,
      currency,
      source_org: dto.providerCode,
      source_account_type: 'WalletId',
      source_account_id: dto.walletNumber,
      beneficiary_org: beneficiaryOrg,
      beneficiary_account_type: beneficiaryAccType,
      beneficiary_account_id: beneficiaryAccId,
      status: PaymentStatus.CREATED,
      metadata: dto.metadata || {},
    });

    // 3. Log state
    await this.logAudit(paymentId, 'CREATED', null, PaymentStatus.CREATED);

    // 4. Transition to INITIATING
    await this.updateStatus(paymentId, PaymentStatus.CREATED, PaymentStatus.INITIATING);

    try {
      // 5. Build initiate payloads
      const clientRequestId = generateRequestId();
      const clientRefNumber = generateReferenceNumber();

      const tharwattPayload = {
        requestId: clientRequestId,
        currencyCode: currency,
        amount: dto.amount,
        amountType: 1,
        isBeneficiaryInitiated: true,
        referenceNumber: clientRefNumber,
        source: {
          organizationCode: dto.providerCode,
          accountType: 'ProfileId',
          AccountId: dto.walletNumber,
          firstName: 'Customer',
          secondName: '',
          thirdName: '',
          lastName: 'User',
          mobile: dto.walletNumber,
        },
        notes: `Payment for order ${dto.orderId}`,
        description: 'Subscription Payment',
        metaData: [
          { key: 'cvv', value: '' },
          { key: 'orderId', value: dto.orderId },
          { key: 'executionMode', value: 'MANUAL' },
          { key: 'merchantId', value: beneficiaryAccId },
          { key: 'type', value: 'Bill' },
        ],
      };

      let entity: any;
      let responseCode = '0000';
      let responseMessage = 'Initiated';
      const apiProfile = this.config.get<string>('link.apiProfile') || 'tharwatt';

      // 6. Call exactly one configured Link API profile. Never fall back to a
      // different protocol and never manufacture a successful response.
      if (apiProfile === 'tharwatt') {
        const rawRes = await this.linkClient.postRaw('/api/payment/ecommerce/initiate/', tharwattPayload);
        if (!rawRes?.success || !['2000', '0000'].includes(String(rawRes.responseCode || ''))) {
          throw new LinkApiError(
            String(rawRes?.responseCode || 'LINK_INITIATE_REJECTED'),
            rawRes?.message || 'Link rejected payment initiation',
            rawRes,
          );
        }
        const statement = rawRes.statement || rawRes.entity;
        const resourceToken = statement?.reSourceToken || statement?.resourceToken || rawRes.reSourceToken || rawRes.resourceToken;
        if (!statement || !resourceToken) {
          throw new LinkApiError(
            'LINK_INITIATE_RESPONSE_INVALID',
            'Link initiation response is missing statement/resource token',
            rawRes,
          );
        }
        entity = {
          ...statement,
          requestId: statement.requestId || clientRequestId,
          referenceNumber: statement.referenceNumber || clientRefNumber,
          reSourceToken: resourceToken,
          amount: statement.amount ?? dto.amount,
          currencyCode: statement.currencyCode || currency,
        };
        responseCode = String(rawRes.responseCode);
        responseMessage = rawRes.message || 'Initiated';
      } else {
        const initiateBody: LinkInitiateRequest = {
          requestId: clientRequestId,
          referenceNumber: clientRefNumber,
          currencyCode: currency,
          amount: dto.amount,
          amountType: 2,
          captureMode: 'MANUAL',
          isBeneficiaryInitiated: true,
          source: {
            organizationCode: dto.providerCode,
            accountType: 'WalletId',
            accountId: dto.walletNumber,
          },
          beneficiary: {
            organizationCode: beneficiaryOrg,
            accountType: beneficiaryAccType,
            accountId: beneficiaryAccId,
          },
          senderKYC: {},
          receiverKYC: {},
          notes: `Payment for order ${dto.orderId}`,
          metaData: [
            { key: 'orderId', value: dto.orderId },
            { key: 'appId', value: dto.appId },
          ],
        };
        const response = await this.linkClient.post<LinkInitiateResponse>(
          '/v1/transactionrequests',
          HEADERS.initiatePayment(),
          initiateBody,
        );
        entity = response.entity;
        responseCode = response.responseCode;
        responseMessage = response.message || 'Initiated';
        if (!entity?.reSourceToken) {
          throw new LinkApiError(
            response.responseCode || 'LINK_INITIATE_RESPONSE_INVALID',
            response.message || 'Initiate response resource token missing',
            response,
          );
        }
      }

    const initiateFees = entity.fees ?? feesResult.fees;
    const initiateComm = entity.commission ?? feesResult.commission;

      // 7. Store gateway transaction
      await this.db.insert<GatewayTransactionRecord>('gateway_transactions', {
        id: generateRequestId(),
        payment_id: paymentId,
        gateway: 'LINK',
        operation_type: OperationType.INITIATE,
        client_request_id: clientRequestId,
        client_reference_number: clientRefNumber,
        gateway_request_id: entity.requestId,
        gateway_reference_number: entity.referenceNumber,
        resource_token: entity.reSourceToken,
        unified_token: entity.unifiedToken,
        amount: entity.amount ?? dto.amount,
        fees: initiateFees,
        commission: initiateComm,
        currency: entity.currencyCode || currency,
        http_status: 200,
        gateway_success: true,
        response_code: responseCode,
        response_message: responseMessage,
        expires_at: entity.expiryDate,
        transaction_at: entity.transactionDate,
        request_payload: maskPayload(tharwattPayload),
        response_payload: maskPayload(entity),
      });

      // 8. Update payment with initiate data
      await this.db.update('payments', paymentId, {
        fees: initiateFees,
        commission: initiateComm,
        total_amount: dto.amount + initiateFees + initiateComm,
        initiated_at: new Date().toISOString(),
      });

      // 9. Transition to OTP_REQUIRED
      await this.updateStatus(paymentId, PaymentStatus.INITIATING, PaymentStatus.OTP_REQUIRED);

      this.logger.log(
        `Payment ${paymentId} initiated. Waiting for OTP. Token: ${entity.reSourceToken ? entity.reSourceToken.slice(0, 6) : 'N/A'}...`,
      );

      return {
        success: true,
        paymentId,
        status: PaymentStatus.OTP_REQUIRED,
        fees: initiateFees,
        commission: initiateComm,
        totalAmount: dto.amount + initiateFees + initiateComm,
        expiresAt: entity.expiryDate,
      };
    } catch (error) {
      // Initiate failed → mark payment as FAILED
      await this.updateStatus(paymentId, PaymentStatus.INITIATING, PaymentStatus.FAILED);
      await this.db.update('payments', paymentId, {
        failure_reason: (error as Error).message,
        failed_at: new Date().toISOString(),
      });

      throw error;
    }
  }

  // ══════════════════════════════════════════
  // 2. CONFIRM PAYMENT (OTP)
  // ══════════════════════════════════════════

  async confirmPayment(paymentId: string, dto: ConfirmPaymentDto) {
    // 1. Load payment
    const payment = await this.getPaymentOrThrow(paymentId);

    // 2. Validate state
    if (!canConfirm(payment.status as PaymentStatus)) {
      throw new InvalidStateError(paymentId, payment.status, 'confirm');
    }

    // 3. Get the initiate transaction to retrieve tokens
    const initiateTx = await this.getInitiateTransaction(paymentId);

    if (!initiateTx) {
      throw new Error(`No initiate transaction found for payment ${paymentId}`);
    }

    // 4. Check expiry
    if (initiateTx.expires_at && new Date(initiateTx.expires_at) < new Date()) {
      await this.updateStatus(paymentId, PaymentStatus.OTP_REQUIRED, PaymentStatus.EXPIRED);
      throw new PaymentExpiredError(paymentId);
    }

    if (!initiateTx.resource_token) {
      throw new Error(`Initiate transaction missing resource_token for payment ${paymentId}`);
    }

    // 5. Transition to CONFIRMING
    await this.updateStatus(paymentId, PaymentStatus.OTP_REQUIRED, PaymentStatus.CONFIRMING);

    try {
      // 6. Build confirm request
    const confirmBody: LinkConfirmRequest = {
      requestId: initiateTx.gateway_request_id || initiateTx.client_request_id,
      referenceNumber: initiateTx.gateway_reference_number || initiateTx.client_reference_number,
      currencyCode: payment.currency,
      amount: payment.amount,
      organizationCode: payment.source_org,
      autherizationType: 'Token',
      autherizationId: initiateTx.resource_token,
      oneTimeCode: dto.otp,
      metaData: [
        { key: 'orderId', value: payment.external_order_id },
      ],
    };

    let entity: any;
    let responseSuccess = false;
    let responseCode = '';
    let responseMessage = '';
    const apiProfile = this.config.get<string>('link.apiProfile') || 'tharwatt';

    // 7. Call the configured Link profile
      const tharwattConfirmPayload = {
        referenceNumber: initiateTx.gateway_reference_number || initiateTx.client_reference_number,
        requestId: initiateTx.gateway_request_id || initiateTx.client_request_id,
        currencyCode: payment.currency,
        amount: payment.amount,
        source: {
          organizationCode: payment.source_org,
          sourceType: 'Token',
          sourceId: dto.otp,
        },
        Notes: `Payment confirmation for ${payment.external_order_id}`,
        metaData: [
          { key: 'orderId', value: payment.external_order_id },
          { key: 'executionMode', value: 'MANUAL' },
          { key: 'merchantId', value: payment.beneficiary_account_id },
          { key: 'type', value: 'Bill' },
        ],
      };

      if (apiProfile === 'tharwatt') {
        const rawRes = await this.linkClient.postRaw('/api/payment/confirmpayment/', tharwattConfirmPayload);
        if (!rawRes?.success || !['2000', '0000'].includes(String(rawRes.responseCode || ''))) {
          throw new LinkApiError(
            String(rawRes?.responseCode || 'LINK_CONFIRM_REJECTED'),
            rawRes?.message || 'Link rejected payment confirmation',
            rawRes,
          );
        }
        const statement = rawRes.statement || rawRes.entity;
        const transactionId = statement?.transactionId || statement?.referenceNumber || rawRes.transactionId;
        const transactionStatus = statement?.transactionStatus ?? statement?.status ?? rawRes.transactionStatus;
        if (!statement || !transactionId || transactionStatus === undefined) {
          throw new LinkApiError(
            'LINK_CONFIRM_RESPONSE_INVALID',
            'Link confirmation response is missing transaction id or explicit status',
            rawRes,
          );
        }
        entity = {
          ...statement,
          requestId: statement.requestId || confirmBody.requestId,
          referenceNumber: statement.referenceNumber || confirmBody.referenceNumber,
          transactionId,
          transactionStatus,
          amount: statement.amount ?? payment.amount,
          currencyCode: statement.currencyCode || payment.currency,
        };
        responseSuccess = rawRes.success === true;
        responseCode = String(rawRes.responseCode);
        responseMessage = rawRes.message || 'Success';
      } else {
        const response = await this.linkClient.post<LinkConfirmResponse>(
          '/v1/transactions',
          HEADERS.confirmPayment(),
          confirmBody,
        );

        entity = response.entity;
        responseSuccess = response.success;
        responseCode = response.responseCode;
        responseMessage = response.message || 'Success';
        if (!entity) {
          throw new LinkApiError(
            response.responseCode || '5000',
            response.message || 'Confirm response entity missing',
            response,
          );
        }
      }

      // 8. Store confirm transaction
      await this.db.insert<GatewayTransactionRecord>('gateway_transactions', {
        id: generateRequestId(),
        payment_id: paymentId,
        gateway: 'LINK',
        operation_type: OperationType.CONFIRM,
        client_request_id: confirmBody.requestId,
        client_reference_number: confirmBody.referenceNumber,
        transaction_id: entity.transactionId,
        provider_reference: entity.providerReference,
        amount: entity.amount,
        currency: entity.currencyCode,
        http_status: 200,
        gateway_success: true,
        response_code: responseCode,
        response_message: responseMessage,
        transaction_status: String(entity.transactionStatus),
        transaction_at: entity.transactionDate,
        settlement_at: entity.settlementDate,
        request_payload: maskPayload(confirmBody),
        response_payload: maskPayload(entity),
      });

      // 9. CRITICAL: 4-layer financial validation
      if (isFinancialSuccess({
        httpStatus: 200,
        success: responseSuccess,
        responseCode: responseCode,
        transactionStatus: entity.transactionStatus,
      })) {
        // ✅ SUCCESS
        await this.updateStatus(paymentId, PaymentStatus.CONFIRMING, PaymentStatus.SUCCESS);
        await this.db.update('payments', paymentId, {
          confirmed_at: new Date().toISOString(),
          paid_at: new Date().toISOString(),
        });

        this.logger.log(`✅ Payment ${paymentId} SUCCESS. TransactionId: ${entity.transactionId}`);

        return {
          success: true,
          paymentId,
          status: PaymentStatus.SUCCESS,
          transactionId: entity.transactionId,
          amount: entity.amount,
          paidAt: new Date().toISOString(),
        };
      }

      if (isTransactionPending(entity.transactionStatus)) {
        // ⏳ PENDING
        await this.updateStatus(paymentId, PaymentStatus.CONFIRMING, PaymentStatus.PENDING);
        this.logger.warn(`⏳ Payment ${paymentId} is PENDING. Will check status later.`);

        return {
          success: true,
          paymentId,
          status: PaymentStatus.PENDING,
          message: 'Payment is being processed. Status will be updated automatically.',
        };
      }

      // ❌ FAILED
      await this.updateStatus(paymentId, PaymentStatus.CONFIRMING, PaymentStatus.FAILED);
      await this.db.update('payments', paymentId, {
        failure_reason: `transactionStatus=${entity.transactionStatus}: ${responseMessage}`,
        failed_at: new Date().toISOString(),
      });

      this.logger.error(`❌ Payment ${paymentId} FAILED. Status: ${entity.transactionStatus}`);

      return {
        success: false,
        paymentId,
        status: PaymentStatus.FAILED,
        message: responseMessage || 'Payment failed',
      };
    } catch (error) {
      // ⚠️ IMPORTANT: On error, do NOT retry confirm!
      // Instead, check status first.
      this.logger.error(
        `Confirm error for payment ${paymentId}: ${(error as Error).message}. ` +
        `DO NOT RETRY. Check status instead.`,
      );

      await this.updateStatus(paymentId, PaymentStatus.CONFIRMING, PaymentStatus.PENDING);
      await this.db.update('payments', paymentId, {
        failure_reason: `Confirm error: ${(error as Error).message}. Status unknown.`,
      });

      throw error;
    }
  }

  // ══════════════════════════════════════════
  // 3. CHECK PAYMENT STATUS
  // ══════════════════════════════════════════

  async checkPaymentStatus(paymentId: string) {
    const payment = await this.getPaymentOrThrow(paymentId);

    // If already in terminal state, just return it
    if (isTerminalState(payment.status as PaymentStatus)) {
      return { paymentId, status: payment.status };
    }

    // Get the initiate transaction for the requestId
    const initiateTx = await this.getInitiateTransaction(paymentId);
    if (!initiateTx) {
      return { paymentId, status: payment.status };
    }

    // Query Link for transaction request status
    try {
      const apiProfile = this.config.get<string>('link.apiProfile') || 'tharwatt';
      let response: { success: boolean; responseCode: string; entity?: LinkTransactionRequest };
      if (apiProfile === 'tharwatt') {
        const statusPath = this.config.get<string>('link.statusPath');
        if (!statusPath) {
          throw new LinkApiError(
            'LINK_STATUS_PATH_NOT_CONFIGURED',
            'Payment status endpoint is not configured for the Tharwatt profile',
          );
        }
        const raw = await this.linkClient.getRaw(statusPath, {
          requestId: initiateTx.gateway_request_id || initiateTx.client_request_id,
          referenceNumber: initiateTx.gateway_reference_number || initiateTx.client_reference_number,
        });
        if (!raw?.success) {
          throw new LinkApiError(
            String(raw?.responseCode || 'LINK_STATUS_REJECTED'),
            raw?.message || 'Link status request failed',
            raw,
          );
        }
        response = {
          success: true,
          responseCode: String(raw.responseCode || ''),
          entity: raw.statement || raw.entity,
        };
      } else {
        response = await this.linkClient.get<LinkTransactionRequest>(
          '/v1/transactionRequests',
          HEADERS.getPaymentStatus(),
          { requestId: initiateTx.client_request_id },
        );
      }

      const entity = response.entity;
      if (!entity?.status) {
        throw new LinkApiError(
          'LINK_STATUS_RESPONSE_INVALID',
          'Link status response is missing an explicit payment status',
          response,
        );
      }

      // Store status check
      await this.db.insert('gateway_transactions', {
        id: generateRequestId(),
        payment_id: paymentId,
        gateway: 'LINK',
        operation_type: OperationType.STATUS_CHECK,
        client_request_id: initiateTx.client_request_id,
        client_reference_number: initiateTx.client_reference_number,
        gateway_request_id: entity?.requestId,
        transaction_id: entity?.transactionId,
        http_status: 200,
        gateway_success: true,
        response_code: response.responseCode,
        transaction_status: entity?.status,
        last_status_check_at: new Date().toISOString(),
        response_payload: maskPayload(entity),
      });

      // Update payment status based on response
      if (entity?.status === 'Success' || entity?.status === 'Completed' || entity?.status === '1') {
        await this.updateStatus(paymentId, payment.status as PaymentStatus, PaymentStatus.SUCCESS);
        await this.db.update('payments', paymentId, { paid_at: new Date().toISOString() });
        return { paymentId, status: PaymentStatus.SUCCESS };
      }

      if (entity?.status === 'Rejected' || entity?.status === 'Failed' || entity?.status === '2') {
        await this.updateStatus(paymentId, payment.status as PaymentStatus, PaymentStatus.FAILED);
        await this.db.update('payments', paymentId, {
          failure_reason: `Gateway status: ${entity.status}`,
          failed_at: new Date().toISOString(),
        });
        return { paymentId, status: PaymentStatus.FAILED };
      }

      // Still pending
      return { paymentId, status: PaymentStatus.PENDING };
    } catch (error) {
      this.logger.warn(`Status check failed for ${paymentId}: ${(error as Error).message}`);
      return { paymentId, status: payment.status, error: (error as Error).message };
    }
  }

  // ══════════════════════════════════════════
  // 4. GET PAYMENT
  // ══════════════════════════════════════════

  async getPayment(paymentId: string) {
    const payment = await this.getPaymentOrThrow(paymentId);

    return {
      paymentId: payment.id,
      orderId: payment.external_order_id,
      appId: payment.external_app_id,
      status: payment.status,
      paymentMethod: payment.payment_method,
      providerCode: payment.provider_code,
      amount: payment.amount,
      fees: payment.fees,
      commission: payment.commission,
      totalAmount: payment.total_amount,
      currency: payment.currency,
      createdAt: payment.created_at,
      paidAt: payment.paid_at,
      failureReason: payment.failure_reason,
    };
  }

  // ══════════════════════════════════════════
  // Helpers
  // ══════════════════════════════════════════

  private async getPaymentOrThrow(paymentId: string): Promise<PaymentRecord> {
    const payment = await this.db.findById<PaymentRecord>('payments', paymentId);
    if (!payment) throw new PaymentNotFoundError(paymentId);
    return payment;
  }

  private async getInitiateTransaction(paymentId: string): Promise<GatewayTransactionRecord | null> {
    const txs = await this.db.findMany<GatewayTransactionRecord>('gateway_transactions', {
      payment_id: paymentId,
      operation_type: OperationType.INITIATE,
    });
    return txs[0] || null;
  }

  private async updateStatus(
    paymentId: string,
    from: PaymentStatus,
    to: PaymentStatus,
  ): Promise<void> {
    validateTransition(paymentId, from, to);
    await this.db.update('payments', paymentId, { status: to });
    await this.logAudit(paymentId, 'STATUS_CHANGE', from, to);
  }

  private async logAudit(
    paymentId: string,
    action: string,
    fromStatus: string | null,
    toStatus: string,
    details?: Record<string, unknown>,
  ): Promise<void> {
    try {
      await this.db.insert('payment_audit_log', {
        payment_id: paymentId,
        action,
        from_status: fromStatus,
        to_status: toStatus,
        details: details || {},
      });
    } catch (error) {
      this.logger.warn(`Failed to log audit: ${(error as Error).message}`);
    }
  }
}
