import { Injectable, NestMiddleware, HttpStatus } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Request, Response, NextFunction } from 'express';

/**
 * API Key middleware to protect internal endpoints.
 * Clients must send: X-API-Key: <key>
 *
 * In production a missing API_KEY is a fatal misconfiguration: every request
 * is rejected instead of silently disabling authentication.
 */
@Injectable()
export class ApiKeyMiddleware implements NestMiddleware {
  private readonly apiKey: string;
  private readonly nodeEnv: string;

  constructor(private readonly config: ConfigService) {
    this.apiKey = this.config.get<string>('apiKey') || '';
    this.nodeEnv = this.config.get<string>('nodeEnv') || 'development';
  }

  use(req: Request, res: Response, next: NextFunction) {
    // Skip health check
    if (req.path === '/health' || req.path.endsWith('/payments/logo-proxy')) {
      return next();
    }

    if (!this.apiKey) {
      if (this.nodeEnv === 'production') {
        return res.status(HttpStatus.SERVICE_UNAVAILABLE).json({
          success: false,
          code: 'API_KEY_NOT_CONFIGURED',
          message: 'Gateway API key is not configured',
        });
      }
      // No API key configured — skip validation (dev mode)
      return next();
    }

    const providedKey = req.headers['x-api-key'] as string;

    if (!providedKey || providedKey !== this.apiKey) {
      return res.status(HttpStatus.UNAUTHORIZED).json({
        success: false,
        code: 'INVALID_API_KEY',
        message: 'Missing or invalid API key',
      });
    }

    next();
  }
}
