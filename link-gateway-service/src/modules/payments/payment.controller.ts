import {
  Controller,
  Get,
  Post,
  Param,
  Body,
  Query,
  Res,
  HttpCode,
  HttpStatus,
} from '@nestjs/common';
import { Response } from 'express';
import axios from 'axios';
import * as https from 'https';
import { PaymentOrchestrator } from './payment.orchestrator';
import { CreatePaymentDto, ConfirmPaymentDto, CalculateFeesDto } from './payment.types';
import { FeesService } from '../fees/fees.service';
import { LookupService } from '../lookup/lookup.service';

@Controller('api/v1')
export class PaymentController {
  constructor(
    private readonly orchestrator: PaymentOrchestrator,
    private readonly feesService: FeesService,
    private readonly lookupService: LookupService,
  ) {}

  // ──────────────────────────────────────────
  // Providers (Lookup) & Logo Proxy
  // ──────────────────────────────────────────

  /** Get available payment providers (wallets, banks) */
  @Get('payments/providers')
  async getProviders() {
    const companies = await this.lookupService.getActiveWalletProviders();

    return {
      success: true,
      providers: companies.map((c) => {
        const rawUrl = c.logoUrl || c.imageUrl;
        const proxiedUrl = rawUrl ? `/api/v1/payments/logo-proxy?url=${encodeURIComponent(rawUrl)}` : undefined;
        return {
          code: c.code,
          name: c.name,
          nameEn: c.nameEn,
          logoUrl: proxiedUrl || rawUrl,
          sector: typeof c.sectorType === 'string' ? c.sectorType : 'Wallets',
          isActive: c.isActive,
        };
      }),
    };
  }

  /** Proxy wallet logos safely across all browsers */
  @Get('payments/logo-proxy')
  async getLogoProxy(@Query('url') url: string, @Res() res: Response) {
    if (!url) {
      return res.status(HttpStatus.BAD_REQUEST).send('Missing url');
    }
    try {
      const target = new URL(url);
      const allowedHosts = (process.env.LINK_LOGO_HOSTS || '')
        .split(',')
        .map((host) => host.trim().toLowerCase())
        .filter(Boolean);
      if (target.protocol !== 'https:' || !allowedHosts.includes(target.hostname.toLowerCase())) {
        return res.status(HttpStatus.BAD_REQUEST).send('Logo URL is not allowed');
      }
      const response = await axios.get(url, {
        responseType: 'arraybuffer',
        httpsAgent: new https.Agent({ rejectUnauthorized: true }),
        timeout: 5000,
        maxRedirects: 0,
      });
      const rawContentType = response.headers['content-type'];
      const contentType = typeof rawContentType === 'string' ? rawContentType : 'image/png';
      if (!contentType.toLowerCase().startsWith('image/')) {
        return res.status(HttpStatus.UNSUPPORTED_MEDIA_TYPE).send('URL did not return an image');
      }
      res.setHeader('Content-Type', contentType);
      res.setHeader('Cache-Control', 'public, max-age=86400');
      return res.send(Buffer.from(response.data));
    } catch (err) {
      return res.status(HttpStatus.NOT_FOUND).send('Image not found');
    }
  }

  /** Get provider-specific services */
  @Get('payments/providers/:providerCode/services')
  async getProviderServices(@Param('providerCode') providerCode: string) {
    const services = await this.lookupService.getServices(providerCode);
    return { success: true, services };
  }

  /** Get available currencies for a provider */
  @Get('payments/providers/:providerCode/currencies')
  async getProviderCurrencies(@Param('providerCode') providerCode: string) {
    const currencies = await this.lookupService.getCurrencies(providerCode);
    return { success: true, currencies };
  }

  // ──────────────────────────────────────────
  // Fees
  // ──────────────────────────────────────────

  /** Calculate payment fees before initiating */
  @Post('payments/fees')
  @HttpCode(HttpStatus.OK)
  async calculateFees(@Body() dto: CalculateFeesDto) {
    const result = await this.feesService.getFees(
      dto.providerCode,
      dto.amount,
      dto.currency || 'YER',
      dto.serviceCode,
    );

    return { success: true, ...result };
  }

  // ──────────────────────────────────────────
  // Payment Lifecycle
  // ──────────────────────────────────────────

  /** Create and initiate a new payment */
  @Post('payments')
  @HttpCode(HttpStatus.CREATED)
  async createPayment(@Body() dto: CreatePaymentDto) {
    return this.orchestrator.initiatePayment(dto);
  }

  /** Confirm payment with OTP */
  @Post('payments/:paymentId/confirm')
  @HttpCode(HttpStatus.OK)
  async confirmPayment(
    @Param('paymentId') paymentId: string,
    @Body() dto: ConfirmPaymentDto,
  ) {
    return this.orchestrator.confirmPayment(paymentId, dto);
  }

  /** Get payment details */
  @Get('payments/:paymentId')
  async getPayment(@Param('paymentId') paymentId: string) {
    return this.orchestrator.getPayment(paymentId);
  }

  /** Manually trigger status check for pending payments */
  @Post('payments/:paymentId/check-status')
  @HttpCode(HttpStatus.OK)
  async checkStatus(@Param('paymentId') paymentId: string) {
    return this.orchestrator.checkPaymentStatus(paymentId);
  }

  // ──────────────────────────────────────────
  // Merchant
  // ──────────────────────────────────────────

  /** Get merchant account balance */
  @Get('merchant/balance')
  async getMerchantBalance() {
    // Direct Link API call for balance
    const { LinkClient } = require('../../adapters/link/link.client');
    // This would be better as a separate MerchantService
    return { success: true, message: 'Implement via MerchantService' };
  }
}
