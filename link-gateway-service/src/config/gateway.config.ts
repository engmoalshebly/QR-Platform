// ============================================
// Link Gateway Service Configuration
// ============================================

export default () => ({
  port: parseInt(process.env.PORT || '3000', 10),
  nodeEnv: process.env.NODE_ENV || 'development',

  // ── Supabase ──
  supabase: {
    url: process.env.SUPABASE_URL || '',
    anonKey: process.env.SUPABASE_ANON_KEY || '',
    serviceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY || '',
  },

  // ── Link Unified Gateway ──
  link: {
    baseUrl: process.env.LINK_GATEWAY_BASE_URL || '',
    apiProfile: (process.env.LINK_API_PROFILE || 'tharwatt').toLowerCase(),
    statusPath: process.env.LINK_STATUS_PATH || '',
    fixedFeeYer: parseFloat(process.env.LINK_FIXED_FEE_YER || '0'),
    fixedCommissionYer: parseFloat(process.env.LINK_FIXED_COMMISSION_YER || '0'),
    clientId: process.env.LINK_CLIENT_ID || 'halali-app',
    clientSecret: process.env.LINK_CLIENT_SECRET || '',

    merchant: {
      organizationCode: process.env.LINK_MERCHANT_ORG_CODE || 'Link',
      accountType: process.env.LINK_MERCHANT_ACCOUNT_TYPE || 'MerchantId',
      accountId: process.env.LINK_MERCHANT_ACCOUNT_ID || '',
    },

    // Token settings
    tokenRefreshBuffer: 120, // refresh 120s before expiry
    requestTimeout: parseInt(process.env.LINK_REQUEST_TIMEOUT_MS || '15000', 10),
  },

  // ── Redis ──
  redis: {
    host: process.env.REDIS_HOST || 'localhost',
    port: parseInt(process.env.REDIS_PORT || '6379', 10),
    password: process.env.REDIS_PASSWORD || undefined,
    db: parseInt(process.env.REDIS_DB || '0', 10),
  },

  // ── Internal Security ──
  apiKey: process.env.API_KEY || '',
});
