interface UsageGaugeProps {
  value: number
  max: number
  label: string
  size?: number
}

export function UsageGauge({ value, max, label, size = 100 }: UsageGaugeProps) {
  const strokeWidth = 8
  const radius = (size - strokeWidth) / 2
  const circumference = Math.PI * radius // half circle
  const pct = max > 0 ? Math.min(value / max, 1) : 0
  const dashArray = `${pct * circumference} ${circumference}`
  const cx = size / 2
  const cy = size / 2

  // Color based on usage level
  const color = pct < 0.6 ? '#22C55E' : pct < 0.85 ? '#F59E0B' : '#EF4444'
  const gradientId = `gauge-grad-${label.replace(/\s/g, '')}`

  return (
    <div className="usage-gauge" aria-label={`${label}: ${Math.round(pct * 100)}%`}>
      <svg width={size} height={size * 0.65} viewBox={`0 0 ${size} ${size * 0.65}`} aria-hidden="true">
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#22C55E" />
            <stop offset="60%" stopColor="#F59E0B" />
            <stop offset="100%" stopColor="#EF4444" />
          </linearGradient>
        </defs>

        {/* background arc */}
        <path
          d={`M ${strokeWidth / 2} ${cy} A ${radius} ${radius} 0 0 1 ${size - strokeWidth / 2} ${cy}`}
          fill="none"
          stroke="var(--color-border)"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
        />

        {/* filled arc */}
        <path
          d={`M ${strokeWidth / 2} ${cy} A ${radius} ${radius} 0 0 1 ${size - strokeWidth / 2} ${cy}`}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={dashArray}
          className="gauge-arc"
        />

        {/* center text */}
        <text
          x={cx}
          y={cy - 4}
          textAnchor="middle"
          dominantBaseline="central"
          fill="var(--color-text)"
          fontSize="18"
          fontWeight="700"
          fontFamily="Inter, sans-serif"
        >
          {Math.round(pct * 100)}%
        </text>
      </svg>
      <span className="gauge-label">{label}</span>
    </div>
  )
}
