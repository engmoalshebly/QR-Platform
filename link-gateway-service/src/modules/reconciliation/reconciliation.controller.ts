import { Controller, Get, Query } from '@nestjs/common';
import { ReconciliationService } from './reconciliation.service';

@Controller('api/v1/reconciliation')
export class ReconciliationController {
  constructor(private readonly reconciliationService: ReconciliationService) {}

  /** Query transaction requests */
  @Get('requests')
  async getTransactionRequests(
    @Query('startDate') startDate: string,
    @Query('endDate') endDate: string,
    @Query('status') status?: string,
    @Query('companyCode') companyCode?: string,
  ) {
    const requests = await this.reconciliationService.getTransactionRequests({
      startDate: startDate || new Date().toISOString().split('T')[0],
      endDate: endDate || new Date().toISOString().split('T')[0],
      status,
      companyCode,
    });

    return { success: true, count: requests.length, requests };
  }

  /** Query settled transactions */
  @Get('transactions')
  async getTransactions(
    @Query('startDate') startDate: string,
    @Query('endDate') endDate: string,
    @Query('status') status?: string,
    @Query('take') take?: number,
    @Query('skip') skip?: number,
  ) {
    const transactions = await this.reconciliationService.getTransactions({
      startDate: startDate || new Date().toISOString().split('T')[0],
      endDate: endDate || new Date().toISOString().split('T')[0],
      status,
      take,
      skip,
    });

    return { success: true, count: transactions.length, transactions };
  }

  /** Query single transaction by referenceNumber */
  @Get('transactions/by-reference')
  async getTransactionByReference(@Query('referenceNumber') referenceNumber: string) {
    const transaction = await this.reconciliationService.getTransactionByReference(referenceNumber);
    return { success: true, transaction };
  }
}
