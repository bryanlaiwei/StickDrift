import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'
import { api, type Finding, type GameSession, type Insights, type ResidentDetail as Detail } from '../api'
import { Assistant } from '../components/Assistant'
import { GameVisits } from '../components/GameVisits'
import { ConcernCard, RiskAlert, RiskBadge } from '../components/Insights'
import { RatPoints } from '../components/LiveCharts'
import { LiveNow } from '../components/LiveNow'
import { SessionTable } from '../components/SessionTable'
import { TabPanel, Tabs } from '../components/Tabs'
import { VisitPatterns } from '../components/VisitPatterns'
import { GameTrendCharts, TrendCharts } from '../components/TrendCharts'
import { formatDateTime } from '../format'

function ReportButton({ id }: { id: string }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const run = async () => {
    setBusy(true)
    setErr(null)
    try {
      const { blob, filename } = await api.residentReport(id)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="report-btn">
      <button className="btn btn-secondary btn-small" onClick={run} disabled={busy}>
        {busy ? 'Writing report…' : 'Clinician report (PDF)'}
      </button>
      {err && (
        <p className="error" role="alert">
          {err}
        </p>
      )}
    </div>
  )
}

type TabKey = 'overview' | 'trends' | 'games' | 'ask' | 'history'

export default function ResidentDetail() {
  const { id = '' } = useParams()
  const [data, setData] = useState<Detail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<TabKey>('overview')

  useEffect(() => {
    setData(null)
    setError(null)
    setTab('overview')
    api
      .caregiverResident(id)
      .then(setData)
      .catch((e: Error) => setError(e.message))
  }, [id])

  if (error) {
    return (
      <main className="wrap page-pad">
        <p className="crumb">
          <Link to="/caregiver">← All residents</Link>
        </p>
        <p className="error" role="alert">
          {error}
        </p>
      </main>
    )
  }
  if (data === null) {
    return (
      <main className="wrap page-pad">
        <p className="muted">Loading…</p>
      </main>
    )
  }

  const { insights } = data

  return (
    <main className="wrap page-pad">
      <p className="crumb">
        <Link to="/caregiver">← All residents</Link>
      </p>

      <header className="resident-head">
        <span className="avatar avatar-lg" aria-hidden>
          {data.display_name[0].toUpperCase()}
        </span>
        <div>
          <p className="eyebrow">Resident</p>
          <h1>
            {data.display_name} <RiskBadge risk={insights.risk} />
          </h1>
          <p className="muted">
            {data.dominant_hand === 'unknown' ? 'Dominant hand not set' : `${data.dominant_hand}-handed`} ·{' '}
            {data.sessions.length + data.game_sessions.length} sessions
            {insights.synthetic && <span className="badge badge-synthetic">Includes simulated data</span>}
          </p>
        </div>
        <ReportButton id={data.participant_id} />
      </header>

      <LiveNow participantId={data.participant_id} compact />
      <RiskAlert name={data.display_name} insights={insights} onSeeDetails={() => setTab('overview')} />

      <Tabs<TabKey>
        label="Resident sections"
        value={tab}
        onChange={setTab}
        items={[
          { key: 'overview', label: 'Overview' },
          { key: 'trends', label: 'Trends' },
          { key: 'games', label: 'Game visits', badge: data.game_sessions.length || null },
          { key: 'ask', label: 'Ask the assistant' },
          ...(data.sessions.length > 0
            ? [{ key: 'history' as const, label: 'Earlier sessions', badge: data.sessions.length }]
            : []),
        ]}
      />

      <TabPanel>
        {tab === 'overview' && <Overview data={data} insights={insights} />}
        {tab === 'trends' && <Trends data={data} insights={insights} />}
        {tab === 'games' && <GameVisits visits={data.game_sessions} name={data.display_name} />}
        {tab === 'ask' && (
          <Assistant
            participantId={data.participant_id}
            name={data.display_name}
            suggestions={[
              `Why was ${data.display_name} flagged?`,
              'How has the left hand changed over time?',
              'What should I check first?',
              'Is this resident improving or getting worse?',
            ]}
          />
        )}
        {tab === 'history' && (
          <section className="panel">
            <h2>Earlier sessions</h2>
            <p className="muted panel-lede">Reaction-test sessions recorded before the game lobby, kept for comparison.</p>
            <SessionTable sessions={data.sessions} />
          </section>
        )}
      </TabPanel>
    </main>
  )
}

function glance(f: Finding | undefined) {
  if (!f) return { value: '—', delta: '', bad: false }
  return { value: f.latest_text, delta: `usual ${f.baseline_text}`, bad: f.flagged }
}

function Overview({ data, insights }: { data: Detail; insights: Insights }) {
  const latestGame = data.game_sessions[0]
  const by = new Map(insights.findings.map((f) => [f.key, f]))
  const rows: { label: string; l?: Finding; r?: Finding }[] = [
    { label: 'Response time', l: by.get('left_latency'), r: by.get('right_latency') },
    { label: 'Accuracy', l: by.get('left_accuracy'), r: by.get('right_accuracy') },
  ]

  return (
    <>
      {latestGame && <LatestJudgement visits={data.game_sessions} />}
      {insights.status === 'ok' && (
        <section className="glance" aria-label="Latest session compared with usual">
          {rows.map((row) => (
            <div className="glance-card" key={row.label}>
              <h3>{row.label}</h3>
              {(['l', 'r'] as const).map((k) => {
                const g = glance(row[k])
                return (
                  <p key={k} className={g.bad ? 'is-flagged' : ''}>
                    <i style={{ background: `var(--hand-${k === 'l' ? 'left' : 'right'})` }} aria-hidden />
                    <span className="sr-only">{k === 'l' ? 'Left' : 'Right'}</span>
                    <strong>{g.value}</strong>
                    <span className="muted">{g.delta}</span>
                  </p>
                )
              })}
            </div>
          ))}
        </section>
      )}

      {insights.concerns.length > 0 ? (
        <section id="concerns" aria-label="Potential health concerns">
          <p className="muted section-note">{insights.disclaimer}</p>
          <div className="concern-list">
            {insights.concerns.map((c) => (
              <ConcernCard key={c.id} concern={c} />
            ))}
          </div>
        </section>
      ) : (
        <section className="panel calm">
          <h2>All in line</h2>
          <p className="muted">
            Nothing has moved enough from {data.display_name}’s usual pattern to flag. Look at Trends to see how each
            measurement has moved over time.
          </p>
        </section>
      )}
    </>
  )
}

function LatestJudgement({ visits }: { visits: GameSession[] }) {
  const visit = visits[0]
  const rat = visit.visit?.games?.rat
  return (
    <section className="panel judge judge-done">
      <h2>
        Latest visit <span className="muted section-sub">{formatDateTime(visit.started_at)}</span>
      </h2>
      <VisitPatterns visits={visits} />
      {rat && <RatPoints rat={rat} />}
    </section>
  )
}

type TrendMode = 'games' | 'earlier'

function Trends({ data, insights }: { data: Detail; insights: Insights }) {
  const modes = [
    { key: 'games' as const, label: 'Game visits', badge: data.game_sessions.length },
    { key: 'earlier' as const, label: 'Earlier sessions', badge: data.sessions.length },
  ].filter((m) => m.badge > 0)
  const [mode, setMode] = useState<TrendMode>(modes[0]?.key ?? 'earlier')

  return (
    <section className="panel">
      {modes.length > 1 && <Tabs variant="pills" label="Which game" value={mode} onChange={setMode} items={modes} />}
      {mode === 'games' ? (
        <>
          <p className="muted panel-lede">Each point is one visit to the game lobby, oldest on the left.</p>
          <GameTrendCharts visits={data.game_sessions} />
        </>
      ) : (
        <>
          <p className="muted panel-lede">
            Each point is one session. The dashed line is their usual level; a red ring marks a reading that moved
            enough to count as a change.
          </p>
          <TrendCharts sessions={data.sessions} insights={insights} />
        </>
      )}
    </section>
  )
}
