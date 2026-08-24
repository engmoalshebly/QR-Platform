import { Injectable, Logger } from '@nestjs/common';
import { LinkClient } from '../../adapters/link/link.client';
import { HEADERS } from '../../adapters/link/link.headers';
import { LinkTransaction, LinkTransactionRequest } from '../../adapters/link/link.types';

export interface ReconciliationQueryParams {
  startDate: string; // Format: YYYY/MM/DD or YYYY-MM-DD
  endDate: string;
  status?: string;
  companyCode?: string;
  take?: number;
  skip?: number;
}

@Injectable()
export class ReconciliationService {
  private readonly logger = new Logger(ReconciliationService.name);

  constructor(private readonly linkClient: LinkClient) {}

  /**
   * Query all transaction requests from Link
   * GET /v1/transactionRequests (requests / all)
   */
  async getTransactionRequests(query: ReconciliationQueryParams): Promise<LinkTransactionRequest[]> {
    this.logger.debug(`Reconciliation: querying requests between ${query.startDate} and ${query.endDate}`);

    const params: Record<string, string | number> = {
      startDate: query.startDate,
      endDate: query.endDate,
    };

    if (query.status) params.status = query.status;
    if (query.companyCode) params.companyCode = query.companyCode;

    const response = await this.linkClient.get<LinkTransactionRequest>(
      '/v1/transactionRequests',
      HEADERS.getAllTransactionRequests(),
      params,
    );

    return response.entities || (response.entity ? [response.entity] : []);
  }

  /**
   * Query all executed transactions from Link
   * GET /v1/transactions (transactions / all)
   */
  async getTransactions(query: ReconciliationQueryParams): Promise<LinkTransaction[]> {
    this.logger.debug(`Reconciliation: querying transactions between ${query.startDate} and ${query.endDate}`);

    const params: Record<string, string | number> = {
      startDate: query.startDate,
      endDate: query.endDate,
      take: query.take || 50,
      skip: query.skip || 0,
    };

    if (query.status) params.status = query.status;

    const response = await this.linkClient.get<LinkTransaction>(
      '/v1/transactions',
      HEADERS.getAllTransactions(),
      params,
    );

    return response.entities || (response.entity ? [response.entity] : []);
  }

  /**
   * Query a single transaction by referenceNumber
   * GET /v1/transactions?referenceNumber=...
   */
  async getTransactionByReference(referenceNumber: string): Promise<LinkTransaction | null> {
    const response = await this.linkClient.get<LinkTransaction>(
      '/v1/transactions',
      HEADERS.getTransaction(),
      { referenceNumber },
    );

    return response.entity || null;
  }
}
