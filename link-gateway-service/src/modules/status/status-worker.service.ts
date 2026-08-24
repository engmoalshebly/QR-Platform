import { Injectable, Logger } from '@nestjs/common';
import { Cron, CronExpression } from '@nestjs/schedule';
import { DatabaseService } from '../../config/database.service';
import { PaymentOrchestrator } from '../payments/payment.orchestrator';
import { PaymentRecord } from '../payments/payment.types';
import { PaymentStatus } from '../../config/constants';

@Injectable()
export class StatusWorkerService {
  private readonly logger = new Logger(StatusWorkerService.name);
  private isRunning = false;

  constructor(
    private readonly db: DatabaseService,
    private readonly orchestrator: PaymentOrchestrator,
  ) {}

  /**
   * Periodic job: checks all pending / checking payments.
   * Runs every 30 seconds.
   */
  @Cron(CronExpression.EVERY_30_SECONDS)
  async handlePendingPayments() {
    if (this.isRunning) {
      return;
    }

    this.isRunning = true;

    try {
      // Find payments in PENDING or CHECKING status
      const pendingPayments = await this.db.findMany<PaymentRecord>('payments', {
        status: PaymentStatus.PENDING,
      }, { limit: 20 });

      if (pendingPayments.length === 0) {
        return;
      }

      this.logger.log(`Found ${pendingPayments.length} pending payments. Checking statuses...`);

      for (const payment of pendingPayments) {
        try {
          const result = await this.orchestrator.checkPaymentStatus(payment.id);
          this.logger.debug(`Status check for payment ${payment.id}: ${result.status}`);
        } catch (err) {
          this.logger.error(`Failed to check status for payment ${payment.id}: ${(err as Error).message}`);
        }
      }
    } catch (error) {
      this.logger.error(`Status worker error: ${(error as Error).message}`);
    } finally {
      this.isRunning = false;
    }
  }
}
