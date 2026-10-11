/**
 * Plans are priced and stored in USD (migration_v69). YER is extremely
 * volatile and split across two de-facto exchange rates (Aden "new note"
 * vs Sana'a "old note"), so it is never the stored price -- only a display
 * estimate computed from this constant. Update the rate here periodically;
 * last set from the Aden parallel-market rate (~1,565–1,600 YER/USD,
 * September 2026). No migration needed to change it.
 */
export const USD_TO_YER_RATE = 1600

export function formatUsd(amount: number): string {
  return amount === 0 ? '0' : amount.toLocaleString('en-US')
}

export function usdToYer(amountUsd: number): number {
  return Math.round(amountUsd * USD_TO_YER_RATE)
}

export function formatYer(amountUsd: number): string {
  return usdToYer(amountUsd).toLocaleString('en-US')
}
