import { useMemo } from 'react'

interface SparklineChartProps {
  data: number[]
  width?: number
  height?: number
  color?: string
  id?: string
}

export function SparklineChart({
  data,
  width = 120,
  height = 36,
  color = '#D4A32C',
  id = 'sparkline',
}: SparklineChartProps) {
  const { linePath, areaPath } = useMemo(() => {
    if (!data.length) return { linePath: '', areaPath: '' }

    const padding = 2
    const w = width - padding * 2
    const h = height - padding * 2
    const min = Math.min(...data)
    const max = Math.max(...data)
    const range = max - min || 1

    const points = data.map((v, i) => ({
      x: padding + (i / (data.length - 1)) * w,
      y: padding + h - ((v - min) / range) * h,
    }))

    const line = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ')
    const area = `${line} L${points[points.length - 1].x},${height} L${points[0].x},${height} Z`

    return { linePath: line, areaPath: area }
  }, [data, width, height])

  if (!data.length) return null

  const gradientId = `spark-grad-${id}`

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="sparkline-svg"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.3} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      <path d={areaPath} fill={`url(#${gradientId})`} className="sparkline-area" />
      <path
        d={linePath}
        fill="none"
        stroke={color}
        strokeWidth={1.8}
        strokeLinecap="round"
        strokeLinejoin="round"
        className="sparkline-line"
      />
    </svg>
  )
}
