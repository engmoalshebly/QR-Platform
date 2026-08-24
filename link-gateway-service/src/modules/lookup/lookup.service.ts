import { Injectable, Logger } from '@nestjs/common';
import { LinkClient } from '../../adapters/link/link.client';
import { HEADERS } from '../../adapters/link/link.headers';
import { RedisService } from '../../config/redis.service';
import { LOOKUP_CACHE_TTL, REDIS_KEYS } from '../../config/constants';
import { DatabaseService } from '../../config/database.service';
import { ConfigService } from '@nestjs/config';
import {
  LinkCompany,
  LinkCurrency,
  LinkService,
  LinkInstrument,
} from '../../adapters/link/link.types';

@Injectable()
export class LookupService {
  private readonly logger = new Logger(LookupService.name);

  constructor(
    private readonly linkClient: LinkClient,
    private readonly redis: RedisService,
    private readonly db: DatabaseService,
    private readonly config: ConfigService,
  ) {}

  // ──────────────────────────────────────────
  // Companies (Payment Providers)
  // ──────────────────────────────────────────

  async getCompanies(companyCode?: string): Promise<LinkCompany[]> {
    const cacheKey = `${REDIS_KEYS.LOOKUP_PREFIX}companies:${companyCode || 'all'}`;

    // Try cache
    const cached = await this.redis.getJson<LinkCompany[]>(cacheKey);
    if (cached) return cached;

    // Fetch from Link
    const params: Record<string, string> = {};
    if (companyCode) params.companyCode = companyCode;

    const apiProfile = this.config.get<string>('link.apiProfile') || 'tharwatt';
    if (apiProfile === 'tharwatt') {
      const rawRes = await this.linkClient.getRaw('/api/payment/services/');
      if (!rawRes?.success || !Array.isArray(rawRes.entities)) {
        throw new Error(rawRes?.message || 'Invalid services response from Link');
      }
      const mapped: LinkCompany[] = rawRes.entities.map((item: any, idx: number) => ({
        id: idx + 1,
        code: item.code,
        name: item.name,
        nameAr: item.name,
        nameEn: item.nameEn || item.name,
        logoUrl: item.imageUrl,
        sectorType: item.sectorType || 'Wallets',
        isActive: item.isActive !== false,
      }));
      await this.redis.setJson(cacheKey, mapped, LOOKUP_CACHE_TTL);
      await this.syncCompaniesToDb(mapped);
      this.logger.log(`Fetched ${mapped.length} live services from Tharwatt Link Gateway`);
      return mapped;
    }

    const response = await this.linkClient.get<LinkCompany>(
      '/v1/data',
      HEADERS.getCompanies(),
      params,
    );
    const companies = response.entities || [];
    await this.redis.setJson(cacheKey, companies, LOOKUP_CACHE_TTL);
    await this.syncCompaniesToDb(companies);
    this.logger.log(`Fetched ${companies.length} companies from Link`);
    return companies;
  }

  /** Get only active wallet providers (for payment method selection) */
  async getActiveWalletProviders(): Promise<LinkCompany[]> {
    const all = await this.getCompanies();
    return all.filter((c) => c.isActive && (c.sectorType === 0 || c.sectorType === 'Wallets'));
  }

  // ──────────────────────────────────────────
  // Currencies
  // ──────────────────────────────────────────

  async getCurrencies(companyCode?: string): Promise<LinkCurrency[]> {
    const cacheKey = `${REDIS_KEYS.LOOKUP_PREFIX}currencies:${companyCode || 'all'}`;
    const cached = await this.redis.getJson<LinkCurrency[]>(cacheKey);
    if (cached) return cached;

    const params: Record<string, string> = {};
    if (companyCode) params.companyCode = companyCode;

    const response = await this.linkClient.get<LinkCurrency>(
      '/v1/data',
      HEADERS.getCurrencies(),
      params,
    );

    const currencies = response.entities || [];
    await this.redis.setJson(cacheKey, currencies, LOOKUP_CACHE_TTL);

    return currencies;
  }

  // ──────────────────────────────────────────
  // Services
  // ──────────────────────────────────────────

  async getServices(companyCode?: string): Promise<LinkService[]> {
    const cacheKey = `${REDIS_KEYS.LOOKUP_PREFIX}services:${companyCode || 'all'}`;
    const cached = await this.redis.getJson<LinkService[]>(cacheKey);
    if (cached) return cached;

    const params: Record<string, string> = {};
    if (companyCode) params.companyCode = companyCode;

    const response = await this.linkClient.get<LinkService>(
      '/v1/data',
      HEADERS.getServices(),
      params,
    );

    const services = response.entities || [];
    await this.redis.setJson(cacheKey, services, LOOKUP_CACHE_TTL);

    return services;
  }

  // ──────────────────────────────────────────
  // Instruments
  // ──────────────────────────────────────────

  async getInstruments(companyCode?: string): Promise<LinkInstrument[]> {
    const cacheKey = `${REDIS_KEYS.LOOKUP_PREFIX}instruments:${companyCode || 'all'}`;
    const cached = await this.redis.getJson<LinkInstrument[]>(cacheKey);
    if (cached) return cached;

    const params: Record<string, string> = {};
    if (companyCode) params.companyCode = companyCode;

    const response = await this.linkClient.get<LinkInstrument>(
      '/v1/data',
      HEADERS.getInstruments(),
      params,
    );

    const instruments = response.entities || [];
    await this.redis.setJson(cacheKey, instruments, LOOKUP_CACHE_TTL);

    return instruments;
  }

  // ──────────────────────────────────────────
  // DB Sync
  // ──────────────────────────────────────────

  private async syncCompaniesToDb(companies: LinkCompany[]): Promise<void> {
    try {
      for (const company of companies) {
        const existing = await this.db.findMany('gateway_providers', {
          gateway: 'LINK',
          code: company.code,
        });

        const data = {
          gateway: 'LINK',
          code: company.code,
          name_ar: company.name,
          name_en: company.nameEn,
          logo_url: company.imageUrl || null,
          is_active: company.isActive,
          business_type: company.businessType,
          sector_type: typeof company.sectorType === 'string'
            ? company.sectorType
            : company.sectorType === 0 ? 'Wallets'
            : company.sectorType === 1 ? 'Banks'
            : company.sectorType === 3 ? 'Remittances'
            : 'Other',
          last_synced_at: new Date().toISOString(),
        };

        if (existing.length > 0) {
          await this.db.update('gateway_providers', (existing[0] as any).id, data);
        } else {
          await this.db.insert('gateway_providers', data);
        }
      }
    } catch (error) {
      this.logger.warn(`Failed to sync companies to DB: ${(error as Error).message}`);
    }
  }

  /** Force refresh all lookup data */
  async refreshAll(): Promise<void> {
    this.logger.log('Refreshing all lookup data...');
    await Promise.allSettled([
      this.getCompanies(),
      this.getCurrencies(),
      this.getServices(),
      this.getInstruments(),
    ]);
    this.logger.log('Lookup refresh complete');
  }
}
