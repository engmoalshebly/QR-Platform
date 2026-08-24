import { IsString, IsNumber, IsOptional, Min } from 'class-validator';

export class IssueVoucherDto {
  @IsString()
  orderId: string;

  @IsString()
  providerCode: string;

  @IsString()
  walletNumber: string;

  @IsNumber()
  @Min(1)
  amount: number;

  @IsOptional()
  @IsString()
  currency?: string;

  @IsOptional()
  metadata?: Record<string, string>;
}

export class CaptureVoucherDto {
  @IsString()
  requestId: string;

  @IsString()
  referenceNumber: string;

  @IsString()
  organizationCode: string;

  @IsString()
  tokenId: string; // reSourceToken

  @IsNumber()
  @Min(1)
  amount: number;

  @IsOptional()
  @IsString()
  currency?: string;

  @IsOptional()
  @IsString()
  oneTimeCode?: string;
}
