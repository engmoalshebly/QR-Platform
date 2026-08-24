import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import type { LucideIcon } from 'lucide-react'
import { SparklineChart } from './SparklineChart'

interface StatCardProps {
  title: string
  value: number
  formatted?: string
  delta: string
  deltaType?: 'positive' | 'neutral' | 'negative'
  icon: LucideIcon
  tone?: 'gold' | 'green' | 'blue' | 'red' | 'purple'
  sparkData?: number[]
  index?: number
}

const TONE_MAP: Record<string, { bg: string; border: string; color: string; spark: string }> = {
  gold:   { bg: 'rgba(201,169,110,0.10)', border: 'rgba(201,169,110,0.25)', color: '#DFC08A', spark: '#C9A96E' },
  green:  { bg: 'rgba(34,197,94,0.10)',   border: 'rgba(34,197,94,0.25)',   color: '#4ade80', spark: '#22C55E' },
  blue:   { bg: 'rgba(59,130,246,0.10)',  border: 'rgba(59,130,246,0.25)',  color: '#60a5fa', spark: '#3B82F6' },
  red:    { bg: 'rgba(239,68,68,0.10)',   border: 'rgba(239,68,68,0.25)',   color: '#f87171', spark: '#EF4444' },
  purple: { bg: 'rgba(139,92,246,0.10)',  border: 'rgba(139,92,246,0.25)',  color: '#a78bfa', spark: '#8B5CF6' },
}

const DELTA_COLORS: Record<string, string> = {
  positive: '#4ade80',
  negative: '#f87171',
  neutral:  '#94A3B8',
}

function useCountUp(target: number, duration = 1200) {
  const [count, setCount] = useState(0)
  const rafRef = useRef<number>(0)

  useEffect(() => {
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (prefersReducedMotion) {
      setCount(target)
      return
    }

    let start: number | null = null
    const step = (ts: number) => {
      if (!start) start = ts
      const elapsed = ts - start
      const progress = Math.min(elapsed / duration, 1)
      // ease-out quad
      const eased = 1 - (1 - progress) * (1 - progress)
      setCount(Math.round(eased * target))
      if (progress < 1) {
        rafRef.current = requestAnimationFrame(step)
      }
    }
    rafRef.current = requestAnimationFrame(step)
    return () => cancelAnimationFrame(rafRef.current)
  }, [target, duration])

  return count
}

const numberFmt = new Intl.NumberFormat('ar')

export function StatCard({
  title,
  value,
  formatted,
  delta,
  deltaType = 'neutral',
  icon: Icon,
  tone = 'gold',
  sparkData,
  index = 0,
}: StatCardProps) {
  const animatedValue = useCountUp(value)
  const t = TONE_MAP[tone] || TONE_MAP.gold

  return (
    <motion.div
      className="stat-card"
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: index * 0.08, ease: [0, 0, 0.2, 1] }}
      whileHover={{ y: -3, transition: { duration: 0.2 } }}
      style={{ '--stat-border': t.border } as React.CSSProperties}
    >
      <div className="stat-card__top">
        <div className="stat-card__icon" style={{ background: t.bg, color: t.color }}>
          <Icon size={20} />
        </div>
        <span className="stat-card__title">{title}</span>
      </div>

      <div className="stat-card__body">
        <strong className="stat-card__value">
          {formatted ?? numberFmt.format(animatedValue)}
        </strong>
        {sparkData && sparkData.length > 1 && (
          <SparklineChart data={sparkData} color={t.spark} id={`stat-${tone}-${index}`} />
        )}
      </div>

      <span className={`stat-card__delta stat-card__delta--${deltaType}`} style={{ color: DELTA_COLORS[deltaType] }}>
        {deltaType === 'positive' && '↑ '}
        {deltaType === 'negative' && '↓ '}
        {delta}
      </span>
    </motion.div>
  )
}
