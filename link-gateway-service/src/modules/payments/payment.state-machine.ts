import { Logger } from '@nestjs/common';
import { PaymentStatus } from '../../config/constants';
import { InvalidStateError } from '../../shared/errors';

/**
 * Payment State Machine
 *
 * Defines all valid state transitions for a payment lifecycle.
 * Prevents invalid transitions (e.g., confirming an already-paid payment).
 */

/** Map of valid transitions: currentStatus → allowed next statuses */
const VALID_TRANSITIONS: Record<PaymentStatus, PaymentStatus[]> = {
  [PaymentStatus.CREATED]:    [PaymentStatus.INITIATING, PaymentStatus.CANCELLED],
  [PaymentStatus.INITIATING]: [PaymentStatus.OTP_REQUIRED, PaymentStatus.FAILED],
  [PaymentStatus.OTP_REQUIRED]: [PaymentStatus.CONFIRMING, PaymentStatus.EXPIRED, PaymentStatus.CANCELLED],
  [PaymentStatus.CONFIRMING]: [PaymentStatus.SUCCESS, PaymentStatus.FAILED, PaymentStatus.PENDING],
  [PaymentStatus.PENDING]:    [PaymentStatus.CHECKING, PaymentStatus.EXPIRED],
  [PaymentStatus.CHECKING]:   [PaymentStatus.SUCCESS, PaymentStatus.FAILED, PaymentStatus.PENDING, PaymentStatus.UNKNOWN],
  // Terminal states — no further transitions
  [PaymentStatus.SUCCESS]:    [],
  [PaymentStatus.FAILED]:     [],
  [PaymentStatus.EXPIRED]:    [],
  [PaymentStatus.CANCELLED]:  [],
  [PaymentStatus.UNKNOWN]:    [PaymentStatus.CHECKING],
};

const logger = new Logger('PaymentStateMachine');

/**
 * Validate if a state transition is allowed.
 * @throws InvalidStateError if transition is not valid
 */
export function validateTransition(
  paymentId: string,
  currentStatus: PaymentStatus,
  nextStatus: PaymentStatus,
): void {
  const allowed = VALID_TRANSITIONS[currentStatus];

  if (!allowed || !allowed.includes(nextStatus)) {
    logger.error(
      `Invalid transition: ${currentStatus} → ${nextStatus} for payment ${paymentId}`,
    );
    throw new InvalidStateError(paymentId, currentStatus, `transition to ${nextStatus}`);
  }

  logger.debug(`State transition: ${currentStatus} → ${nextStatus} for payment ${paymentId}`);
}

/**
 * Check if a payment is in a terminal (final) state
 */
export function isTerminalState(status: PaymentStatus): boolean {
  return [
    PaymentStatus.SUCCESS,
    PaymentStatus.FAILED,
    PaymentStatus.EXPIRED,
    PaymentStatus.CANCELLED,
  ].includes(status);
}

/**
 * Check if a payment can accept OTP confirmation
 */
export function canConfirm(status: PaymentStatus): boolean {
  return status === PaymentStatus.OTP_REQUIRED;
}

/**
 * Check if a payment needs status polling
 */
export function needsStatusCheck(status: PaymentStatus): boolean {
  return [PaymentStatus.PENDING, PaymentStatus.UNKNOWN].includes(status);
}
