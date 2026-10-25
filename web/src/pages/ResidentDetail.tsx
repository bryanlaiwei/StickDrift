import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'
import { api, type Visit, type Insights, type ResidentDetail as Detail } from '../api'
import { Assistant } from '../components/Assistant'
import { GameVisits } from '../components/GameVisits'
import { ConcernCard, RiskAlert, RiskBadge } from '../components/Insights'
import { RatPoints } from '../components/LiveCharts'
import { LiveNow } from '../components/LiveNow'
import { TabPanel, Tabs } from '../components/Tabs'
import { VisitPatterns } from '../components/VisitPatterns'
import { GameTrendCharts } from '../components/TrendCharts'
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

type TabKey = 'overview' | 'trends' | 'games' | 'ask'

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
            {data.visits.length} {data.visits.length === 1 ? 'visit' : 'visits'}
          </p>
        </div>
        <ReportButton id={data.resident_id} />
      </header>

      <LiveNow residentId={data.resident_id} compact />
      <RiskAlert name={data.display_name} insights={insights} onSeeDetails={() => setTab('overview')} />

      <Tabs<TabKey>
        label="Resident sections"
        value={tab}
        onChange={setTab}
        items={[
          { key: 'overview', label: 'Overview' },
          { key: 'trends', label: 'Trends' },
          { key: 'games', label: 'Game visits', badge: data.visits.length || null },
          { key: 'ask', label: 'Ask the assistant' },
        ]}
      />

      <TabPanel>
        {tab === 'overview' && <Overview data={data} insights={insights} />}
        {tab === 'trends' && <Trends visits={data.visits} />}
        {tab === 'games' && <GameVisits visits={data.visits} name={data.display_name} />}
        {tab === 'ask' && (
          <Assistant
            residentId={data.resident_id}
            name={data.display_name}
            suggestions={[
              `Why was ${data.display_name} flagged?`,
              'How has the left hand changed over time?',
              'What should I check first?',
              'Is this resident improving or getting worse?',
            ]}
          />
        )}
      </TabPanel>
    </main>
  )
}

function Overview({ data, insights }: { data: Detail; insights: Insights }) {
  const latestGame = data.visits[0]

  return (
    <>
      {latestGame && <LatestJudgement visits={data.visits} />}
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

function LatestJudgement({ visits }: { visits: Visit[] }) {
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

function Trends({ visits }: { visits: Visit[] }) {
  return (
    <section className="panel">
      <p className="muted panel-lede">Each point is one visit to the game lobby, oldest on the left.</p>
      <GameTrendCharts visits={visits} />
    </section>
  )
}
