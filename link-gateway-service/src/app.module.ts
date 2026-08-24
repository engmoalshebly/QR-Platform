import { Module, MiddlewareConsumer, NestModule } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { ScheduleModule } from '@nestjs/schedule';

// Config
import gatewayConfig from './config/gateway.config';
import { DatabaseService } from './config/database.service';
import { RedisService } from './config/redis.service';

// Adapters
import { LinkClient } from './adapters/link/link.client';

// Services
import { LookupService } from './modules/lookup/lookup.service';
import { FeesService } from './modules/fees/fees.service';
import { PaymentOrchestrator } from './modules/payments/payment.orchestrator';
import { StatusWorkerService } from './modules/status/status-worker.service';
import { MerchantService } from './modules/merchant/merchant.service';
import { VoucherService } from './modules/vouchers/voucher.service';
import { ReconciliationService } from './modules/reconciliation/reconciliation.service';

// Controllers
import { PaymentController } from './modules/payments/payment.controller';
import { MerchantController } from './modules/merchant/merchant.controller';
import { VoucherController } from './modules/vouchers/voucher.controller';
import { ReconciliationController } from './modules/reconciliation/reconciliation.controller';

// Middleware
import { ApiKeyMiddleware } from './middleware/api-key.middleware';

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      load: [gatewayConfig],
      envFilePath: ['.env', '.env.local'],
    }),
    ScheduleModule.forRoot(),
  ],
  controllers: [
    PaymentController,
    MerchantController,
    VoucherController,
    ReconciliationController,
  ],
  providers: [
    // Infrastructure
    DatabaseService,
    RedisService,

    // Adapters
    LinkClient,

    // Services
    LookupService,
    FeesService,
    PaymentOrchestrator,
    StatusWorkerService,
    MerchantService,
    VoucherService,
    ReconciliationService,
  ],
})
export class AppModule implements NestModule {
  configure(consumer: MiddlewareConsumer) {
    consumer
      .apply(ApiKeyMiddleware)
      .forRoutes('api/*');
  }
}
