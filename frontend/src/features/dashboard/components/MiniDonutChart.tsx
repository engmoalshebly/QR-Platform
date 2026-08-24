import { useMemo } from 'react'

interface DonutSegment {
  value: number
  color: string
  label?: string
}

interface MiniDonutChartProps {
  segments: DonutSegment[]
  size?: number
  strokeWidth?: number
  centerLabel?: string
  centerValue?: string
}

export function MiniDonutChart({
  segments,
  size = 120,
  strokeWidth = 10,
  centerLabel,
  centerValue,
}: MiniDonutChartProps) {
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const cx = size / 2
  const cy = size / 2

  const total = useMemo(() => segments.reduce((s, seg) => s + seg.value, 0), [segments])

  const arcs = useMemo(() => {
    let accumulated = 0
    return segments.map((seg) => {
      const pct = total > 0 ? seg.value / total : 0
      const dashArray = `${pct * circumference} ${circumference}`
      const rotation = (accumulated / total) * 360
      accumulated += seg.value
      return { ...seg, dashArray, rotation, pct }
    })
  }, [segments, total, circumference])

  if (!total) {
    return (
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <circle
          cx={cx}
          cy={cy}
          r={radius}
          fill="none"
          stroke="var(--color-border)"
          strokeWidth={strokeWidth}
        />
        <text x={cx} y={cy} textAnchor="middle" dominantBaseline="central" fill="var(--color-text-muted)" fontSize="12">
          لا بيانات
        </text>
      </svg>
    )
  }

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      className="donut-svg"
      aria-hidden="true"
    >
      {/* background track */}
      <circle
        cx={cx}
        cy={cy}
        r={radius}
        fill="none"
        stroke="var(--color-border)"
        strokeWidth={strokeWidth}
      />

      {/* segments */}
      {arcs.map((arc, i) => (
        <circle
          key={i}
          cx={cx}
          cy={cy}
          r={radius}
          fill="none"
          stroke={arc.color}
          strokeWidth={strokeWidth}
          strokeDasharray={arc.dashArray}
          strokeDashoffset={0}
          strokeLinecap="round"
          transform={`rotate(${-90 + arc.rotation} ${cx} ${cy})`}
          className="donut-segment"
          style={{ animationDelay: `${i * 120}ms` }}
        />
      ))}

      {/* center text */}
      {centerValue && (
        <>
          <text
            x={cx}
            y={cy - 6}
            textAnchor="middle"
            dominantBaseline="central"
            fill="var(--color-text)"
            fontSize="20"
            fontWeight="700"
            fontFamily="Inter, sans-serif"
          >
            {centerValue}
          </text>
          {centerLabel && (
            <text
              x={cx}
              y={cy + 14}
              textAnchor="middle"
              dominantBaseline="central"
              fill="var(--color-text-muted)"
              fontSize="10"
            >
              {centerLabel}
            </text>
          )}
        </>
      )}
    </svg>
  )
}
