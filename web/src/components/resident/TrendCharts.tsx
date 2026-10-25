import { useId, useState } from 'react'
import type { Visit, HandLive } from '../../api'
import { visitLabels } from '../../format'
import { Tabs } from '../ui/Tabs'

interface Series {
  label: string
  color: string
  /** One value per x point; null means no data that visit. */
  points: (number | null)[]
}

interface LineChartProps {
  title: string
  caption: string
  xLabels: string[]
  series: Series[]
  format: (v: number) => string
  yMin?: number
  yMax?: number
}

const W = 720
const H = 280
const PAD = { top: 26, right: 20, bottom: 44, left: 60 }

function LineChart({ title, caption, xLabels, series, format, yMin, yMax }: LineChartProps) {
  const titleId = useId()
  const descId = useId()
  const values = series.flatMap((s) => s.points.filter((p): p is number => p != null))
  const dataMin = values.length ? Math.min(...values) : 0
  const dataMax = values.length ? Math.max(...values) : 1
  const span = Math.max(dataMax - dataMin, 1e-6)
  const yLo = yMin ?? dataMin - span * 0.15
  const yHi = yMax ?? dataMax + span * 0.15

  const plotW = W - PAD.left - PAD.right
  const plotH = H - PAD.top - PAD.bottom
  const n = xLabels.length
  const step = n <= 1 ? plotW : plotW / (n - 1)
  const x = (i: number) => PAD.left + (n <= 1 ? plotW / 2 : step * i)
  const y = (v: number) => PAD.top + plotH * (1 - (v - yLo) / (yHi - yLo))
  const ticks = Array.from({ length: 5 }, (_, i) => yLo + ((yHi - yLo) * i) / 4)
  const labelEvery = Math.max(1, Math.ceil(n / 6))

  return (
    <figure className="chart">
      <figcaption>
        <strong>{title}</strong>
        <span className="muted">{caption}</span>
      </figcaption>
      <div className="chart-legend">
        {series.map((s) => (
          <span key={s.label} className="chart-key">
            <span className="chart-swatch" style={{ background: s.color }} aria-hidden />
            {s.label}
          </span>
        ))}
      </div>
      <svg
        className="chart-svg"
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-labelledby={`${titleId} ${descId}`}
        preserveAspectRatio="xMidYMid meet"
      >
        <title id={titleId}>{title}</title>
        <desc id={descId}>{caption}</desc>

        {ticks.map((t, i) => (
          <g key={i}>
            <line className="chart-grid" x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} />
            <text className="chart-axis" x={PAD.left - 10} y={y(t)} textAnchor="end" dominantBaseline="middle">
              {format(t)}
            </text>
          </g>
        ))}

        {xLabels.map((label, i) =>
          // the first and last points are always labelled; drop a regular label that would crowd the last one
          i === 0 || i === n - 1 || (i % labelEvery === 0 && n - 1 - i >= Math.max(2, labelEvery * 0.75)) ? (
            <text
              key={i}
              className="chart-axis"
              x={x(i)}
              y={H - PAD.bottom + 22}
              textAnchor={n > 1 && i === n - 1 ? 'end' : n > 1 && i === 0 ? 'start' : 'middle'}
            >
              {label}
            </text>
          ) : null,
        )}

        {series.map((s) => {
          const pts = s.points.map((v, i) => (v == null ? null : ([x(i), y(v)] as const)))
          let d = ''
          let pen = false
          for (const p of pts) {
            if (p == null) {
              pen = false
              continue
            }
            d += `${pen ? 'L' : 'M'}${p[0].toFixed(1)} ${p[1].toFixed(1)} `
            pen = true
          }
          return (
            <g key={s.label}>
              <path className="chart-line" d={d} style={{ stroke: s.color }} />
              {pts.map((p, i) =>
                p == null ? null : (
                  <g key={i}>
                    <circle className="chart-dot" cx={p[0]} cy={p[1]} r={n === 1 ? 7 : 4.5} style={{ fill: s.color }}>
                      <title>{`${s.label} · ${xLabels[i]}: ${format(s.points[i] as number)}`}</title>
                    </circle>
                    {n === 1 && (
                      <text className="chart-axis" x={p[0] + 14} y={p[1]} dominantBaseline="middle">
                        {format(s.points[i] as number)}
                      </text>
                    )}
                  </g>
                ),
              )}
            </g>
          )
        })}
      </svg>
      {n === 1 && <p className="hint">This is the first visit. A line appears once there is a second one to compare.</p>}
    </figure>
  )
}

type GameKey = 'apple' | 'fish' | 'rat'
const GAME_TABS: { key: GameKey; label: string }[] = [
  { key: 'apple', label: 'Apple Picking' },
  { key: 'fish', label: 'Harbour Fishing' },
  { key: 'rat', label: 'Rat Catching' },
]

/** One line per hand across web lobby visits, for the headline measurement of each game. */
export function GameTrendCharts({ visits }: { visits: Visit[] }) {
  const ordered = visits.slice().reverse()
  const played = (g: GameKey) => ordered.filter((v) => v.games[g])
  const [view, setView] = useState<GameKey>(() => GAME_TABS.find((t) => played(t.key).length >= 2)?.key ?? 'apple')
  const rows = played(view)
  const pick = (k: keyof HandLive) => (h: 'left' | 'right') => rows.map((v) => v.games[view]!.hands[h][k] ?? null)
  const chart = {
    apple: {
      title: 'Time to pick an apple',
      caption: 'Median time from an apple being free to pick until that hand’s glove grabbed it, per visit. Lower is quicker.',
      format: (v: number) => `${v.toFixed(2)} s`,
      points: pick('reach_s'),
      yMin: 0,
      yMax: undefined,
    },
    fish: {
      title: 'Time on the fishing lane',
      caption: 'Share of each trace the lure stayed on the glowing lane, per visit. Higher is steadier.',
      format: (v: number) => `${Math.round(v * 100)}%`,
      points: pick('on_target'),
      yMin: 0,
      yMax: 1,
    },
    rat: {
      title: 'Time to slam a target rat',
      caption: 'Median time from the target rat appearing until the stick was flicked up, per visit. Lower is quicker.',
      format: (v: number) => `${v.toFixed(2)} s`,
      points: pick('reach_s'),
      yMin: 0,
      yMax: undefined,
    },
  }[view]

  return (
    <div className="chart-single">
      <Tabs
        variant="pills"
        label="Game chart"
        value={view}
        onChange={setView}
        items={GAME_TABS.map((t) => ({ ...t, badge: played(t.key).length || null }))}
      />
      {rows.length < 1 ? (
        <p className="muted">
          This chart appears after the first visit that includes {GAME_TABS.find((t) => t.key === view)!.label}.
        </p>
      ) : (
        <LineChart
          title={chart.title}
          caption={chart.caption}
          xLabels={visitLabels(rows.map((v) => v.started_at))}
          yMin={chart.yMin}
          yMax={chart.yMax}
          format={chart.format}
          series={[
            { label: 'Left hand', color: 'var(--hand-left)', points: chart.points('left') },
            { label: 'Right hand', color: 'var(--hand-right)', points: chart.points('right') },
          ]}
        />
      )}
    </div>
  )
}
