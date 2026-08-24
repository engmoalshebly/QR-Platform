import { Injectable, OnModuleInit, OnModuleDestroy, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import Redis from 'ioredis';

@Injectable()
export class RedisService implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(RedisService.name);
  private client: Redis | null = null;
  private isConnected = false;
  private readonly memoryCache = new Map<string, { value: string; expiresAt?: number }>();

  constructor(private readonly config: ConfigService) {}

  async onModuleInit() {
    try {
      this.client = new Redis({
        host: this.config.get<string>('redis.host') || '127.0.0.1',
        port: this.config.get<number>('redis.port') || 6379,
        password: this.config.get<string>('redis.password') || undefined,
        db: this.config.get<number>('redis.db') || 0,
        retryStrategy: () => null, // don't loop indefinitely
        maxRetriesPerRequest: 1,
        lazyConnect: true,
      });

      this.client.on('error', (err) => {
        this.isConnected = false;
      });

      this.client.on('connect', () => {
        this.isConnected = true;
        this.logger.log('Redis connected successfully');
      });

      await this.client.connect().catch(() => {
        this.isConnected = false;
        this.logger.warn('Redis connection failed, using in-memory cache fallback');
      });
    } catch {
      this.isConnected = false;
      this.logger.warn('Redis initialized with in-memory fallback');
    }
  }

  async onModuleDestroy() {
    if (this.client && this.isConnected) {
      await this.client.quit().catch(() => {});
    }
  }

  async get(key: string): Promise<string | null> {
    if (this.isConnected && this.client) {
      try {
        return await this.client.get(key);
      } catch {
        // fallback to memory
      }
    }
    const item = this.memoryCache.get(key);
    if (!item) return null;
    if (item.expiresAt && Date.now() > item.expiresAt) {
      this.memoryCache.delete(key);
      return null;
    }
    return item.value;
  }

  async set(key: string, value: string, ttlSeconds?: number): Promise<void> {
    if (this.isConnected && this.client) {
      try {
        if (ttlSeconds) {
          await this.client.setex(key, ttlSeconds, value);
        } else {
          await this.client.set(key, value);
        }
        return;
      } catch {
        // fallback to memory
      }
    }
    const expiresAt = ttlSeconds ? Date.now() + ttlSeconds * 1000 : undefined;
    this.memoryCache.set(key, { value, expiresAt });
  }

  async del(key: string): Promise<void> {
    if (this.isConnected && this.client) {
      try {
        await this.client.del(key);
      } catch {
        // ignore
      }
    }
    this.memoryCache.delete(key);
  }

  async exists(key: string): Promise<boolean> {
    const val = await this.get(key);
    return val !== null;
  }

  /** Get JSON-parsed value */
  async getJson<T>(key: string): Promise<T | null> {
    const raw = await this.get(key);
    if (!raw) return null;
    try {
      return JSON.parse(raw) as T;
    } catch {
      return null;
    }
  }

  /** Set JSON-stringified value */
  async setJson<T>(key: string, value: T, ttlSeconds?: number): Promise<void> {
    await this.set(key, JSON.stringify(value), ttlSeconds);
  }
}
