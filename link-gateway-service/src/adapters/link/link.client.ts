import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import axios, { AxiosInstance, AxiosRequestConfig, AxiosError } from 'axios';
import { LinkResponse, LinkAuthToken } from './link.types';
import { LinkHeaders } from './link.headers';
import { LinkApiError, LinkConnectionError, LinkAuthError } from '../../shared/errors';
import { maskToken } from '../../shared/utils';
import { RedisService } from '../../config/redis.service';
import { REDIS_KEYS } from '../../config/constants';

/**
 * Low-level HTTP client for Link Unified Gateway.
 *
 * Responsibilities:
 *   1. Manage Bearer token lifecycle (auto-refresh)
 *   2. Inject X-API-* headers into every request
 *   3. Retry on transient failures (not on financial operations)
 *   4. Log requests/responses for debugging
 */
@Injectable()
export class LinkClient {
  private readonly logger = new Logger(LinkClient.name);
  private readonly http: AxiosInstance;
  private readonly baseUrl: string;
  private readonly clientId: string;
  private readonly clientSecret: string;
  private readonly tokenRefreshBuffer: number;

  constructor(
    private readonly config: ConfigService,
    private readonly redis: RedisService,
  ) {
    this.baseUrl = this.config.get<string>('link.baseUrl') || '';
    this.clientId = this.config.get<string>('link.clientId') || 'halali-app';
    this.clientSecret = this.config.get<string>('link.clientSecret') || '';
    this.tokenRefreshBuffer = this.config.get<number>('link.tokenRefreshBuffer') || 120;

    this.http = axios.create({
      baseURL: this.baseUrl,
      timeout: this.config.get<number>('link.requestTimeout') || 3000,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  // ──────────────────────────────────────────
  // Token Management
  // ──────────────────────────────────────────

  /**
   * Get a valid access token, refreshing if needed.
   * Tokens are cached in Redis with TTL = expires_in - buffer.
   */
  async getAccessToken(): Promise<string> {
    try {
      // Check Redis cache
      const cachedToken = await this.redis.get(REDIS_KEYS.ACCESS_TOKEN);
      const expiresAt = await this.redis.get(REDIS_KEYS.TOKEN_EXPIRES_AT);

      if (cachedToken && expiresAt) {
        const expiryTime = parseInt(expiresAt, 10);
        const now = Math.floor(Date.now() / 1000);

        if (now < expiryTime - this.tokenRefreshBuffer) {
          return cachedToken;
        }
      }
    } catch (err) {
      this.logger.warn(`Redis token read failed, falling back to direct auth: ${(err as Error).message}`);
    }

    // Refresh token
    return this.authenticate();
  }

  /**
   * Authenticate with Link and store the token.
   * POST /accounts/v1/authenticate/token
   */
  private async authenticate(): Promise<string> {
    this.logger.log('Authenticating with Link Gateway...');

    try {
      const response = await this.http.post<LinkResponse<LinkAuthToken>>(
        '/accounts/v1/authenticate/token',
        new URLSearchParams({
          grant_type: 'client_credentials',
          client_id: this.clientId,
          client_secret: this.clientSecret,
        }).toString(),
        {
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        },
      );

      const data = response.data;

      if (!data.success || !data.entity?.access_token) {
        throw new LinkAuthError(
          `Authentication failed: ${data.message || data.responseCode}`,
        );
      }

      const { access_token, expires_in } = data.entity;
      const ttl = Math.max(expires_in - this.tokenRefreshBuffer, 60);
      const expiresAt = Math.floor(Date.now() / 1000) + expires_in;

      // Store in Redis if available
      try {
        await this.redis.set(REDIS_KEYS.ACCESS_TOKEN, access_token, ttl);
        await this.redis.set(REDIS_KEYS.TOKEN_EXPIRES_AT, expiresAt.toString(), ttl);
      } catch (redisErr) {
        this.logger.warn(`Failed to cache token in Redis: ${(redisErr as Error).message}`);
      }

      this.logger.log(
        `Authenticated successfully. Token: ${maskToken(access_token)}, expires in ${expires_in}s`,
      );

      return access_token;
    } catch (error) {
      if (error instanceof LinkAuthError) throw error;
      if (error instanceof AxiosError && error.response) {
        throw new LinkAuthError(
          `Authentication failed with HTTP ${error.response.status}`,
        );
      }
      throw new LinkAuthError(
        `Authentication connection failed: ${(error as Error).message}`,
      );
    }
  }

  // ──────────────────────────────────────────
  // HTTP Methods
  // ──────────────────────────────────────────

  /**
   * Execute a GET request to Link API
   */
  async get<T>(
    path: string,
    linkHeaders: LinkHeaders,
    params?: Record<string, string | number>,
  ): Promise<LinkResponse<T>> {
    const token = await this.getAccessToken();

    const config: AxiosRequestConfig = {
      headers: {
        ...linkHeaders,
        Authorization: `Bearer ${token}`,
      },
      params,
    };

    return this.executeRequest<T>('GET', path, config);
  }

  /**
   * Execute a POST request to Link API
   */
  async post<T>(
    path: string,
    linkHeaders: LinkHeaders,
    body: unknown,
  ): Promise<LinkResponse<T>> {
    const token = await this.getAccessToken();

    const config: AxiosRequestConfig = {
      headers: {
        ...linkHeaders,
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
    };

    return this.executeRequest<T>('POST', path, config, body);
  }

  /**
   * Direct GET request without auth headers (for open Tharwatt endpoints)
   */
  async getRaw<T = any>(path: string, params?: Record<string, string | number>): Promise<T> {
    const response = await this.http.get<T>(path, { params });
    return response.data;
  }

  /**
   * Direct POST request without auth headers (for Tharwatt checkout endpoints)
   */
  async postRaw<T = any>(path: string, body: unknown): Promise<T> {
    const response = await this.http.post<T>(path, body);
    return response.data;
  }

  // ──────────────────────────────────────────
  // Internal
  // ──────────────────────────────────────────

  private async executeRequest<T>(
    method: string,
    path: string,
    config: AxiosRequestConfig,
    body?: unknown,
  ): Promise<LinkResponse<T>> {
    const startTime = Date.now();
    const logPrefix = `[Link ${method} ${path}]`;

    try {
      this.logger.debug(`${logPrefix} Sending request...`);

      const response = method === 'GET'
        ? await this.http.get<LinkResponse<T>>(path, config)
        : await this.http.post<LinkResponse<T>>(path, body, config);

      const duration = Date.now() - startTime;
      const data = response.data;

      this.logger.debug(
        `${logPrefix} ${response.status} in ${duration}ms — success=${data.success}, code=${data.responseCode}`,
      );

      // Link can return HTTP 200 but success=false
      if (!data.success) {
        this.logger.warn(
          `${logPrefix} API returned success=false: ${data.message} (code: ${data.responseCode})`,
        );
        throw new LinkApiError(data.responseCode, data.message || 'Unknown error', data);
      }

      return data;
    } catch (error) {
      const duration = Date.now() - startTime;

      if (error instanceof LinkApiError) throw error;

      if (error instanceof AxiosError) {
        if (error.response) {
          // Server responded with error status
          const data = error.response.data as LinkResponse;
          this.logger.error(
            `${logPrefix} HTTP ${error.response.status} in ${duration}ms: ${data?.message || error.message}`,
          );
          throw new LinkApiError(
            data?.responseCode || String(error.response.status),
            data?.message || error.message,
            data,
          );
        }

        // Network error or timeout
        this.logger.error(`${logPrefix} Connection error in ${duration}ms: ${error.message}`);
        throw new LinkConnectionError(`${error.code}: ${error.message}`);
      }

      throw error;
    }
  }
}
