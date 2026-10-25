import { useId, useState } from 'react'
import type { Concern, Finding, GameSession, HandLive, Insights, MeasureKey, SessionSummary } from '../api'
import { formatDate, visitLabels } from '../format'
import { Tabs } from './Tabs'

interface Series {
  label: string
  color: string
  /** One value per x point; null means no data that session. */
  points: (number | null)[]
  /** The resident's usual level, drawn as a dashed line. */
  baseline?: number | null
  /** Points that moved past the threshold from usual. */
  flagged?: boolean[]
}

interface LineChartProps {
  title: string
  caption: string
  xLabels: string[]
  series: Series[]
  format: (v: number) => string
  yMin?: number
  yMax?: number
  /** First x index of the recent window compared against the baseline. */
  recentFrom?: number
  /** Potential concerns this chart's measurements contribute to. */
  concerns?: Concern[]
  /** Measurements shown in this chart, with their latest-vs-usual change. */
  findings?: Finding[]
  hidden?: boolean
}

const W = 720
const H = 280
const PAD = { top: 26, right: 20, bottom: 44, left: 60 }

function LineChart({ title, caption, xLabels, series, format, yMin, yMax, recentFrom, concerns, findings, hidden }: LineChartProps) {
  const titleId = useId()
  const descId = useId()
  const values = series.flatMap((s) => [
    ...s.points.filter((p): p is number => p != null),
    ...(s.baseline != null ? [s.baseline] : []),
  ])
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
  const anyFlag = series.some((s) => s.flagged?.some(Boolean))
  const shadeX = recentFrom != null && recentFrom > 0 && recentFrom < n ? x(recentFrom) - step / 2 : null
  if (hidden) return null

  return (
    <figure className={`chart ${anyFlag ? 'chart-alert' : ''}`}>
      <figcaption>
        <strong>{title}</strong>
        <span className="muted">{caption}</span>
      </figcaption>
      {concerns && concerns.length > 0 && (
        <div className="chart-tags">
          {concerns.map((c) => (
            <span key={c.id} className={`concern-tag concern-tag-${c.level}`}>
              Contributes to: {c.title}
            </span>
          ))}
        </div>
      )}
      <div className="chart-legend">
        {series.map((s) => (
          <span key={s.label} className="chart-key">
            <span className="chart-swatch" style={{ background: s.color }} aria-hidden />
            {s.label}
          </span>
        ))}
        {series.some((s) => s.baseline != null) && (
          <span className="chart-key">
            <span className="chart-dash" aria-hidden /> Usual level
          </span>
        )}
        {anyFlag && (
          <span className="chart-key">
            <span className="chart-ring" aria-hidden /> Changed from usual
          </span>
        )}
      </div>
      <svg
        className="chart-svg"
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-labelledby={`${titleId} ${descId}`}
        preserveAspectRatio="xMidYMid meet"
      >
        <title id={titleId}>{title}</title>
        <desc id={descId}>
          {caption} {findings?.map((f) => f.text).join(' ')}
        </desc>

        {shadeX != null && (
          <g>
            <rect className="chart-recent" x={shadeX} y={PAD.top} width={W - PAD.right - shadeX} height={plotH} />
            <text className="chart-recent-label" x={shadeX + 6} y={PAD.top - 8}>
              Recent
            </text>
          </g>
        )}

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

        {series.map((s) =>
          s.baseline != null ? (
            <line
              key={`${s.label}-base`}
              className="chart-baseline"
              x1={PAD.left}
              x2={W - PAD.right}
              y1={y(s.baseline)}
              y2={y(s.baseline)}
              style={{ stroke: s.color }}
            />
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
                    {s.flagged?.[i] && <circle className="chart-flag" cx={p[0]} cy={p[1]} r={9} />}
                    <circle className="chart-dot" cx={p[0]} cy={p[1]} r={n === 1 ? 7 : 4.5} style={{ fill: s.color }}>
                      <title>{`${s.label} · ${xLabels[i]}: ${format(s.points[i] as number)}${
                        s.flagged?.[i] ? ' (changed from usual)' : ''
                      }`}</title>
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
      {findings && findings.length > 0 && (
        <ul className="chart-findings">
          {findings.map((f) => (
            <li key={f.key} className={f.flagged ? 'is-flagged' : ''}>
              <span>{f.label}</span>
              <span className="num">
                {f.latest_text} <span className="muted">vs usual {f.baseline_text}</span>{' '}
                <span className={f.flagged ? 'delta-bad' : 'muted'}>({f.change_text})</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </figure>
  )
}

type ChartKey = 'response' | 'accuracy' | 'gap' | 'enjoyment'
const CHART_TABS: { key: ChartKey; label: string }[] = [
  { key: 'response', label: 'Response time' },
  { key: 'accuracy', label: 'Accuracy' },
  { key: 'gap', label: 'Left vs right' },
  { key: 'enjoyment', label: 'Enjoyment' },
]

/** Caregiver trend charts with the resident's usual level, changed points and linked concerns. */
export function TrendCharts({ sessions, insights }: { sessions: SessionSummary[]; insights: Insights }) {
  const [view, setView] = useState<ChartKey>('response')
  const usable = sessions
    .filter((s) => s.status === 'completed' && s.quality !== 'invalid')
    .slice()
    .reverse()

  if (usable.length < 1) {
    return <p className="muted">Charts appear after the first completed session.</p>
  }

  const findings = new Map(insights.findings.map((f) => [f.key, f]))
  const recent = new Set(insights.recent_session_ids)
  const firstRecent = usable.findIndex((s) => recent.has(s.session_id))
  const xLabels = usable.map((s) => formatDate(s.started_at))
  const pct = (c: number | null, v: number | null) => (c != null && v ? Math.round((c / v) * 100) : null)
  const secs = (ms: number | null) => (ms == null ? null : ms / 1000)

  const flaggedFor = (key: MeasureKey) => {
    const ids = new Set(findings.get(key)?.flagged_session_ids ?? [])
    return usable.map((s) => ids.has(s.session_id))
  }
  const base = (key: MeasureKey, scale: (v: number) => number) => {
    const f = findings.get(key)
    return f ? scale(f.baseline) : null
  }
  const linked = (keys: MeasureKey[]) => ({
    concerns: insights.concerns.filter((c) => c.measurements.some((m) => keys.includes(m))),
    findings: keys.map((k) => findings.get(k)).filter((f): f is Finding => f != null),
  })
  const flagged = new Set<ChartKey>()
  for (const f of insights.findings) {
    if (!f.flagged) continue
    flagged.add(f.key === 'lr_gap' ? 'gap' : f.key === 'enjoyment' ? 'enjoyment' : f.kind === 'latency' ? 'response' : 'accuracy')
  }
  const common = { xLabels, recentFrom: firstRecent >= 0 ? firstRecent : undefined }

  return (
    <div className="chart-single">
      <Tabs
        variant="pills"
        label="Chart"
        value={view}
        onChange={setView}
        items={CHART_TABS.map((t) => ({
          ...t,
          badge: flagged.has(t.key) ? <span className="tab-dot" role="img" aria-label="has a change" /> : null,
        }))}
      />
      <LineChart
        {...common}
        hidden={view !== 'response'}
        {...linked(['left_latency', 'right_latency'])}
        title="Response time"
        caption="How quickly each hand responded. Lower is quicker."
        format={(v) => `${v.toFixed(2)} s`}
        series={[
          {
            label: 'Left hand',
            color: 'var(--hand-left)',
            points: usable.map((s) => secs(s.left_median_latency_ms)),
            baseline: base('left_latency', (v) => v / 1000),
            flagged: flaggedFor('left_latency'),
          },
          {
            label: 'Right hand',
            color: 'var(--hand-right)',
            points: usable.map((s) => secs(s.right_median_latency_ms)),
            baseline: base('right_latency', (v) => v / 1000),
            flagged: flaggedFor('right_latency'),
          },
        ]}
      />
      <LineChart
        {...common}
        hidden={view !== 'accuracy'}
        {...linked(['left_accuracy', 'right_accuracy', 'both_accuracy'])}
        title="Accuracy"
        caption="Share of prompts answered correctly each session. Higher is better."
        yMin={0}
        yMax={100}
        format={(v) => `${Math.round(v)}%`}
        series={[
          {
            label: 'Left hand',
            color: 'var(--hand-left)',
            points: usable.map((s) => pct(s.left_correct, s.left_valid)),
            baseline: base('left_accuracy', (v) => v * 100),
            flagged: flaggedFor('left_accuracy'),
          },
          {
            label: 'Right hand',
            color: 'var(--hand-right)',
            points: usable.map((s) => pct(s.right_correct, s.right_valid)),
            baseline: base('right_accuracy', (v) => v * 100),
            flagged: flaggedFor('right_accuracy'),
          },
          {
            label: 'Both hands',
            color: 'var(--hand-both)',
            points: usable.map((s) => pct(s.both_correct, s.both_valid)),
            flagged: flaggedFor('both_accuracy'),
          },
        ]}
      />
      <LineChart
        {...common}
        hidden={view !== 'gap'}
        {...linked(['lr_gap'])}
        title="Left–right difference"
        caption="Left-hand minus right-hand response time. A new gap means one hand changed and the other didn't."
        format={(v) => `${v >= 0 ? '+' : ''}${v.toFixed(2)} s`}
        series={[
          {
            label: 'Left minus right',
            color: 'var(--hand-left)',
            points: usable.map((s) =>
              s.left_median_latency_ms != null && s.right_median_latency_ms != null
                ? (s.left_median_latency_ms - s.right_median_latency_ms) / 1000
                : null,
            ),
            baseline: base('lr_gap', (v) => v / 1000),
            flagged: flaggedFor('lr_gap'),
          },
        ]}
      />
      <LineChart
        {...common}
        hidden={view !== 'enjoyment'}
        {...linked(['enjoyment'])}
        title="Enjoyment"
        caption="How much the resident said they enjoyed the session, from 1 to 5."
        yMin={1}
        yMax={5}
        format={(v) => `${Math.round(v)}/5`}
        series={[
          {
            label: 'Enjoyment',
            color: 'var(--ok)',
            points: usable.map((s) => s.enjoyment),
            baseline: base('enjoyment', (v) => v),
            flagged: flaggedFor('enjoyment'),
          },
        ]}
      />
    </div>
  )
}

type GameKey = 'apple' | 'fish' | 'rat'
const GAME_TABS: { key: GameKey; label: string }[] = [
  { key: 'apple', label: 'Apple Picking' },
  { key: 'fish', label: 'Harbour Fishing' },
  { key: 'rat', label: 'Rat Catching' },
]

/** One line per hand across web lobby visits, for the headline measurement of each game. */
export function GameTrendCharts({ visits }: { visits: GameSession[] }) {
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
