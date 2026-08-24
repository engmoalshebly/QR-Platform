import { Injectable, OnModuleInit, OnModuleDestroy, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { createClient, SupabaseClient } from '@supabase/supabase-js';

@Injectable()
export class DatabaseService implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(DatabaseService.name);
  private client!: SupabaseClient;

  constructor(private readonly config: ConfigService) {}

  async onModuleInit() {
    const url = this.config.get<string>('supabase.url') || 'https://placeholder.supabase.co';
    const key = this.config.get<string>('supabase.serviceRoleKey') || 'placeholder-key';

    this.client = createClient(url, key, {
      auth: { persistSession: false },
      db: { schema: 'public' },
    });

    this.logger.log('DatabaseService initialized with Supabase client');
  }

  async onModuleDestroy() {
    // Supabase client doesn't need explicit cleanup
  }

  /** Get the Supabase client for direct queries */
  getClient(): SupabaseClient {
    return this.client;
  }

  // ──────────────────────────────────────────
  // Generic CRUD helpers
  // ──────────────────────────────────────────

  async insert<T = any>(
    table: string,
    data: any,
  ): Promise<T> {
    const { data: result, error } = await this.client
      .from(table)
      .insert(data)
      .select()
      .single();

    if (error) throw new Error(`DB insert [${table}]: ${error.message}`);
    return result as T;
  }

  async update<T = any>(
    table: string,
    id: string,
    data: any,
  ): Promise<T> {
    const { data: result, error } = await this.client
      .from(table)
      .update({ ...data, updated_at: new Date().toISOString() })
      .eq('id', id)
      .select()
      .single();

    if (error) throw new Error(`DB update [${table}]: ${error.message}`);
    return result as T;
  }

  async findById<T = any>(table: string, id: string): Promise<T | null> {
    const { data, error } = await this.client
      .from(table)
      .select('*')
      .eq('id', id)
      .single();

    if (error && error.code !== 'PGRST116') {
      throw new Error(`DB findById [${table}]: ${error.message}`);
    }
    return (data as T) || null;
  }

  async findMany<T = any>(
    table: string,
    filters: Record<string, unknown> = {},
    options?: { limit?: number; offset?: number; orderBy?: string; ascending?: boolean },
  ): Promise<T[]> {
    let query = this.client.from(table).select('*');

    for (const [key, value] of Object.entries(filters)) {
      query = query.eq(key, value);
    }

    if (options?.orderBy) {
      query = query.order(options.orderBy, { ascending: options.ascending ?? false });
    }
    if (options?.limit) query = query.limit(options.limit);
    if (options?.offset) query = query.range(options.offset, options.offset + (options.limit || 50) - 1);

    const { data, error } = await query;
    if (error) throw new Error(`DB findMany [${table}]: ${error.message}`);
    return (data as T[]) || [];
  }

  /** Execute raw SQL via Supabase RPC (for migrations or complex queries) */
  async rpc<T = any>(functionName: string, params?: Record<string, unknown>): Promise<T> {
    const { data, error } = await this.client.rpc(functionName, params);
    if (error) throw new Error(`DB rpc [${functionName}]: ${error.message}`);
    return data as T;
  }
}
