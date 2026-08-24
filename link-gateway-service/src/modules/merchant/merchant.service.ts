import { Injectable, Logger } from '@nestjs/common';
import { LinkClient } from '../../adapters/link/link.client';
import { HEADERS } from '../../adapters/link/link.headers';
import { LinkBalance, LinkConnection } from '../../adapters/link/link.types';

@Injectable()
export class MerchantService {
  private readonly logger = new Logger(MerchantService.name);

  constructor(private readonly linkClient: LinkClient) {}

  /**
   * Get merchant account balance across currencies
   * GET /accounts/v1/balance
   */
  async getBalance(currencyCode: string = 'YER'): Promise<LinkBalance[]> {
    this.logger.debug(`Fetching merchant balance for currency: ${currencyCode}`);

    const response = await this.linkClient.get<LinkBalance>(
      '/accounts/v1/balance',
      {
        'X-API-Domain': 'merchant',
        'X-API-SubDomain': 'balance',
        'X-API-ServiceName': 'get',
      },
      { currencyCode },
    );

    return response.entities || (response.entity ? [response.entity] : []);
  }

  /**
   * Get merchant integration connections
   * GET /v1/data (connections)
   */
  async getConnections(): Promise<LinkConnection[]> {
    this.logger.debug('Fetching merchant connections...');

    const response = await this.linkClient.get<LinkConnection>(
      '/v1/data',
      HEADERS.getMerchantConnections(),
    );

    return response.entities || [];
  }

  /**
   * Get merchant accounts
   * GET /v1/data (accounts)
   */
  async getAccounts(): Promise<any[]> {
    this.logger.debug('Fetching merchant accounts...');

    const response = await this.linkClient.get<any>(
      '/v1/data',
      HEADERS.getMerchantAccounts(),
    );

    return response.entities || [];
  }
}
