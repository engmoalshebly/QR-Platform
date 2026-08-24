const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { validate } = require('class-validator');
const { isFinancialSuccess } = require('../dist/shared/utils');
const { ConfirmPaymentDto } = require('../dist/modules/payments/payment.types');

test('financial success requires explicit Link success and terminal status', () => {
  assert.equal(isFinancialSuccess({
    httpStatus: 200,
    success: true,
    responseCode: '2000',
    transactionStatus: 1,
  }), true);

  assert.equal(isFinancialSuccess({
    httpStatus: 200,
    success: true,
    responseCode: '2000',
  }), false);

  assert.equal(isFinancialSuccess({
    httpStatus: 200,
    success: false,
    responseCode: '2000',
    transactionStatus: 1,
  }), false);
});

test('OTP is required, numeric, and length constrained', async () => {
  const missing = new ConfirmPaymentDto();
  assert.ok((await validate(missing)).length > 0);

  const invalid = Object.assign(new ConfirmPaymentDto(), { otp: '12ab' });
  assert.ok((await validate(invalid)).length > 0);

  const valid = Object.assign(new ConfirmPaymentDto(), { otp: '65454' });
  assert.equal((await validate(valid)).length, 0);
});

test('payment orchestrator contains no simulated-success fallback', () => {
  const source = fs.readFileSync(
    path.join(__dirname, '..', 'src', 'modules', 'payments', 'payment.orchestrator.ts'),
    'utf8',
  );
  assert.equal(source.includes('sandbox simulation'), false);
  assert.equal(source.includes('sandbox-test-token'), false);
  assert.equal(source.includes('TX_${Date.now()}'), false);
});
