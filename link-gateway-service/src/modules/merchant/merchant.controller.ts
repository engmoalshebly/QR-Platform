import { Controller, Get, Query } from '@nestjs/common';
import { MerchantService } from './merchant.service';

@Controller('api/v1/merchant')
export class MerchantController {
  constructor(private readonly merchantService: MerchantService) {}

  /** Get merchant balance */
  @Get('balance')
  async getBalance(@Query('currency') currency?: string) {
    const balances = await this.merchantService.getBalance(currency || 'YER');
    return { success: true, balances };
  }

  /** Get merchant connections */
  @Get('connections')
  async getConnections() {
    const connections = await this.merchantService.getConnections();
    return { success: true, connections };
  }

  /** Get merchant accounts */
  @Get('accounts')
  async getAccounts() {
    const accounts = await this.merchantService.getAccounts();
    return { success: true, accounts };
  }
}
