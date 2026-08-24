import { Controller, Post, Body, HttpCode, HttpStatus } from '@nestjs/common';
import { VoucherService } from './voucher.service';
import { IssueVoucherDto, CaptureVoucherDto } from './voucher.types';

@Controller('api/v1/vouchers')
export class VoucherController {
  constructor(private readonly voucherService: VoucherService) {}

  /** Issue a payment voucher / code */
  @Post('issue')
  @HttpCode(HttpStatus.CREATED)
  async issueVoucher(@Body() dto: IssueVoucherDto) {
    return this.voucherService.issueVoucher(dto);
  }

  /** Capture / Redeem a payment voucher */
  @Post('capture')
  @HttpCode(HttpStatus.OK)
  async captureVoucher(@Body() dto: CaptureVoucherDto) {
    return this.voucherService.captureVoucher(dto);
  }
}
