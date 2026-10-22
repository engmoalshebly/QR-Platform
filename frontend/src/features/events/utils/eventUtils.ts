/**
 * eventUtils.ts
 * Shared constants and utilities for the Events feature.
 * Single source of truth — never duplicate these across pages.
 */
import type { EventStatus } from '../types'

// ── Status Labels (Arabic) ──────────────────────────────────────
export const STATUS_LABELS: Record<EventStatus, string> = {
  draft: 'مسودة',
  published: 'منشورة',
  active: 'نشطة',
  completed: 'مكتملة',
  cancelled: 'ملغاة',
}

// ── Status CSS class suffix ─────────────────────────────────────
export const STATUS_CSS: Record<EventStatus, string> = {
  draft: 'draft',
  published: 'published',
  active: 'active',
  completed: 'completed',
  cancelled: 'cancelled',
}

// ── Status config (label + css) ─────────────────────────────────
export function getStatusConfig(status: EventStatus) {
  return {
    label: STATUS_LABELS[status] ?? status,
    css: STATUS_CSS[status] ?? 'draft',
  }
}

// ── Date Formatters ─────────────────────────────────────────────
export const dateFmtFull = new Intl.DateTimeFormat('ar', {
  weekday: 'long',
  year: 'numeric',
  month: 'long',
  day: 'numeric',
  hour: 'numeric',
  minute: 'numeric',
})

export const dateFmtShort = new Intl.DateTimeFormat('ar', {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
})

export function formatDateFull(iso: string): string {
  try {
    return dateFmtFull.format(new Date(iso))
  } catch {
    return iso
  }
}

export function formatDateShort(iso: string): string {
  try {
    return dateFmtShort.format(new Date(iso))
  } catch {
    return iso
  }
}

// ── Quota helpers ───────────────────────────────────────────────
export function calcOccupancy(used: number, quota: number): number {
  if (quota <= 0) return 0
  return Math.min(100, Math.round((used / quota) * 100))
}

// ── Allowed status transitions ──────────────────────────────────
export const STATUS_TRANSITIONS: Record<EventStatus, EventStatus[]> = {
  draft: ['published'],
  published: ['active', 'cancelled'],
  active: ['completed', 'cancelled'],
  completed: [],
  cancelled: [],
}

export function canTransition(from: EventStatus, to: EventStatus): boolean {
  return STATUS_TRANSITIONS[from]?.includes(to) ?? false
}
