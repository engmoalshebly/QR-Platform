import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { LinkClient } from '../../adapters/link/link.client';
import { HEADERS } from '../../adapters/link/link.headers';
import {
  LinkInitiateRequest,
  LinkInitiateResponse,
  LinkConfirmRequest,
  LinkConfirmResponse,
} from '../../adapters/link/link.types';
import { generateRequestId, generateReferenceNumber } from '../../shared/utils';
import { LinkApiError } from '../../shared/errors';
import { IssueVoucherDto, CaptureVoucherDto } from './voucher.types';

@Injectable()
export class VoucherService {
  private readonly logger = new Logger(VoucherService.name);

  constructor(
    private readonly linkClient: LinkClient,
    private readonly config: ConfigService,
  ) {}

  /**
   * Issue a Payment Code / Token
   * POST /v1/transactionrequests (pos.wallets.vouchers / issue)
   */
  async issueVoucher(dto: IssueVoucherDto) {
    const currency = dto.currency || 'YER';
    const clientRequestId = generateRequestId();
    const clientRefNumber = generateReferenceNumber();

    const beneficiaryOrg = this.config.get<string>('link.merchant.organizationCode') || 'Link';
    const beneficiaryAccType = this.config.get<string>('link.merchant.accountType') || 'MerchantId';
    const beneficiaryAccId = this.config.get<string>('link.merchant.accountId') || '';

    const body: LinkInitiateRequest = {
      requestId: clientRequestId,
      referenceNumber: clientRefNumber,
      currencyCode: currency,
      amount: dto.amount,
      amountType: 1,
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
      notes: `Voucher for order ${dto.orderId}`,
      metaData: [
        { key: 'orderId', value: dto.orderId },
      ],
    };

    const response = await this.linkClient.post<LinkInitiateResponse>(
      '/v1/transactionrequests',
      HEADERS.issueVoucher(),
      body,
    );

    const entity = response.entity;
    if (!entity) {
      throw new LinkApiError(
        response.responseCode || '5000',
        response.message || 'Failed to issue voucher',
        response,
      );
    }

    this.logger.log(`Issued voucher with token: ${entity.reSourceToken}`);

    return {
      success: true,
      requestId: entity.requestId,
      referenceNumber: entity.referenceNumber,
      voucherCode: entity.reSourceToken,
      unifiedToken: entity.unifiedToken,
      amount: entity.amount,
      currency: entity.currencyCode,
      expiryDate: entity.expiryDate,
    };
  }

  /**
   * Capture / Redeem a Payment Code
   * POST /v1/transactions (pos.wallets.vouchers / capture)
   */
  async captureVoucher(dto: CaptureVoucherDto) {
    const currency = dto.currency || 'YER';

    const body: LinkConfirmRequest = {
      requestId: dto.requestId,
      referenceNumber: dto.referenceNumber,
      currencyCode: currency,
      amount: dto.amount,
      organizationCode: dto.organizationCode,
      autherizationType: 'Token',
      autherizationId: dto.tokenId,
      oneTimeCode: dto.oneTimeCode || '',
    };

    const response = await this.linkClient.post<LinkConfirmResponse>(
      '/v1/transactions',
      HEADERS.captureVoucher(),
      body,
    );

    const entity = response.entity;
    if (!entity) {
      throw new LinkApiError(
        response.responseCode || '5000',
        response.message || 'Failed to capture voucher',
        response,
      );
    }

    this.logger.log(`Captured voucher: transactionId=${entity.transactionId}`);

    return {
      success: true,
      transactionId: entity.transactionId,
      amount: entity.amount,
      currency: entity.currencyCode,
      transactionStatus: entity.transactionStatus,
      settlementDate: entity.settlementDate,
      providerReference: entity.providerReference,
    };
  }
}
