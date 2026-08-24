import { Injectable, Logger } from '@nestjs/common';
import { LinkClient } from '../../adapters/link/link.client';
import { HEADERS } from '../../adapters/link/link.headers';
import { LinkFeesResponse } from '../../adapters/link/link.types';
import { LinkApiError } from '../../shared/errors';
import { ConfigService } from '@nestjs/config';

export interface FeesResult {
  amount: number;
  fees: number;
  commission: number;
  totalAmount: number;
  currency: string;
  feeDetails?: {
    sourceFees: number;
    switchFees: number;
    gwFees: number;
    beneficiaryFees: number;
  };
}

@Injectable()
export class FeesService {
  private readonly logger = new Logger(FeesService.name);

  constructor(
    private readonly linkClient: LinkClient,
    private readonly config: ConfigService,
  ) {}

  /**
   * Get fees for a payment operation.
   * GET /v1/fees?CompanyCode=X&payoutCurrencyCode=Y&payoutAmount=Z&serviceCode=S
   */
  async getFees(
    companyCode: string,
    amount: number,
    currencyCode: string = 'YER',
    serviceCode?: string,
  ): Promise<FeesResult> {
    const apiProfile = this.config.get<string>('link.apiProfile') || 'tharwatt';
    if (apiProfile === 'unified') {
      const params: Record<string, string | number> = {
        companyCode,
        payoutCurrencyCode: currencyCode,
        payoutAmount: amount,
      };
      if (serviceCode) params.serviceCode = serviceCode;
      const response = await this.linkClient.get<LinkFeesResponse>(
        '/v1/fees',
        HEADERS.getFees(),
        params,
      );
      if (!response.entity) {
        throw new LinkApiError(
          response.responseCode || 'LINK_FEES_RESPONSE_INVALID',
          response.message || 'Link fees response is missing its entity',
          response,
        );
      }
      const entity = response.entity;
      return {
        amount,
        fees: entity.fees,
        commission: entity.commission,
        totalAmount: amount + entity.fees + entity.commission,
        currency: currencyCode,
        feeDetails: entity.details,
      };
    }

    // Tharwatt direct does not expose a public fee lookup in the supplied
    // contract. These values must match the signed merchant tariff.
    const fees = this.config.get<number>('link.fixedFeeYer') ?? 0;
    const commission = this.config.get<number>('link.fixedCommissionYer') ?? 0;
    return {
      amount,
      fees,
      commission,
      totalAmount: amount + fees + commission,
      currency: currencyCode,
    };
  }
}
