import { NestFactory } from '@nestjs/core';
import { ValidationPipe, Logger } from '@nestjs/common';
import { AppModule } from './app.module';

async function bootstrap() {
  const logger = new Logger('Bootstrap');

  const nodeEnv = process.env.NODE_ENV || 'development';
  const required = ['LINK_GATEWAY_BASE_URL', 'LINK_MERCHANT_ORG_CODE', 'LINK_MERCHANT_ACCOUNT_ID', 'API_KEY'];
  const missing = required.filter((key) => !process.env[key]?.trim());
  if (missing.length > 0) {
    throw new Error(`Missing required gateway configuration: ${missing.join(', ')}`);
  }
  const profile = (process.env.LINK_API_PROFILE || 'tharwatt').toLowerCase();
  if (!['tharwatt', 'unified'].includes(profile)) {
    throw new Error('LINK_API_PROFILE must be either tharwatt or unified');
  }
  if (profile === 'unified' && (!process.env.LINK_CLIENT_ID?.trim() || !process.env.LINK_CLIENT_SECRET?.trim())) {
    throw new Error('LINK_CLIENT_ID and LINK_CLIENT_SECRET are required for unified profile');
  }
  if (nodeEnv === 'production' && !process.env.LINK_STATUS_PATH?.trim()) {
    throw new Error('LINK_STATUS_PATH is required in production so uncertain payments can be reconciled');
  }
  if (nodeEnv === 'production') {
    const baseUrl = new URL(process.env.LINK_GATEWAY_BASE_URL!);
    if (baseUrl.protocol !== 'https:') {
      throw new Error('LINK_GATEWAY_BASE_URL must use HTTPS in production');
    }
    if (/test|sandbox/i.test(baseUrl.hostname)) {
      throw new Error('LINK_GATEWAY_BASE_URL must not point to a test/sandbox host in production');
    }
    if (!process.env.CORS_ORIGINS?.trim()) {
      throw new Error('CORS_ORIGINS is required in production');
    }
    if ((process.env.API_KEY || '').length < 32) {
      throw new Error('API_KEY must contain at least 32 characters in production');
    }
    if (profile === 'tharwatt' && process.env.LINK_FIXED_FEE_YER === undefined) {
      throw new Error('LINK_FIXED_FEE_YER is required for the Tharwatt production profile');
    }
  }

  const app = await NestFactory.create(AppModule, {
    logger: ['error', 'warn', 'log', 'debug'],
  });

  // Global validation pipe — auto-validates all DTOs
  app.useGlobalPipes(
    new ValidationPipe({
      whitelist: true,          // Strip unknown properties
      forbidNonWhitelisted: true,
      transform: true,          // Auto-transform types
      transformOptions: {
        enableImplicitConversion: true,
      },
    }),
  );

  // CORS for frontend access
  const allowedOrigins = (process.env.CORS_ORIGINS || '')
    .split(',')
    .map((origin) => origin.trim())
    .filter(Boolean);
  app.enableCors({
    origin: nodeEnv === 'production' ? allowedOrigins : true,
    methods: 'GET,POST,PUT,DELETE',
    allowedHeaders: 'Content-Type,Authorization,X-API-Key',
  });

  // Health check endpoint
  const httpAdapter = app.getHttpAdapter();
  httpAdapter.get('/health', (req, res) => {
    res.json({
      status: 'ok',
      service: 'link-gateway-service',
      timestamp: new Date().toISOString(),
    });
  });

  const port = process.env.PORT || 3000;
  await app.listen(port);

  logger.log(`══════════════════════════════════════════`);
  logger.log(`  🚀 Link Gateway Service is running`);
  logger.log(`  📡 Port: ${port}`);
  logger.log(`  🌍 Environment: ${process.env.NODE_ENV || 'development'}`);
  logger.log(`  🔗 Health: http://localhost:${port}/health`);
  logger.log(`  📚 API Base: http://localhost:${port}/api/v1`);
  logger.log(`══════════════════════════════════════════`);
}

bootstrap();
