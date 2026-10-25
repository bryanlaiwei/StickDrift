import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { api, type ResidentRow } from '../api'
import { Assistant } from '../components/Assistant'
import { RiskBadge } from '../components/Insights'
import { LiveNow } from '../components/LiveNow'
import { formatDateTime } from '../format'

export default function CaregiverDashboard() {
  const [rows, setRows] = useState<ResidentRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .caregiverResidents()
      .then(setRows)
      .catch((e: Error) => setError(e.message))
  }, [])

  const atRisk = rows?.filter((r) => r.risk !== 'none').length ?? 0

  return (
    <main className="wrap page-pad">
      <header className="page-title">
        <p className="eyebrow">Care team</p>
        <h1>Residents</h1>
        {rows && (
          <p className="muted">
            {rows.length} {rows.length === 1 ? 'resident' : 'residents'} ·{' '}
            {atRisk > 0 ? (
              <strong className="text-bad">{atRisk} worth a look</strong>
            ) : (
              'nobody flagged right now'
            )}
          </p>
        )}
      </header>

      <LiveNow />

      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : rows === null ? (
        <p className="muted">Loading…</p>
      ) : (
        <>
          <div className="resident-grid">
            {rows.map((r) => (
              <Link
                key={r.resident_id}
                to={`/caregiver/residents/${r.resident_id}`}
                className={`resident-card ${r.risk !== 'none' ? `resident-card-flag resident-card-${r.risk}` : ''}`}
              >
                <div className="resident-card-head">
                  <span className="avatar" aria-hidden>
                    {r.display_name[0].toUpperCase()}
                  </span>
                  <div>
                    <span className="resident-name">{r.display_name}</span>
                    <span className="resident-meta">
                      {r.dominant_hand === 'unknown' ? 'hand not set' : `${r.dominant_hand}-handed`} · {r.visit_count}{' '}
                      {r.visit_count === 1 ? 'visit' : 'visits'}
                    </span>
                  </div>
                  <RiskBadge risk={r.risk} />
                </div>
                {r.risk !== 'none' ? (
                  <p className="resident-flag">
                    <strong>{r.concerns[0]?.title}</strong>
                    {r.concerns.length > 1 && <span className="muted"> +{r.concerns.length - 1} more</span>}
                    {r.review.reasons[0] && <span className="resident-reason">{r.review.reasons[0]}</span>}
                  </p>
                ) : (
                  <p className="resident-ok">In line with their usual pattern</p>
                )}
                <p className="resident-foot muted">
                  {r.last_played_at ? `Last played ${formatDateTime(r.last_played_at)}` : 'Not played yet'}
                </p>
              </Link>
            ))}
          </div>

          <details className="tool">
            <summary>Ask the care assistant</summary>
            <Assistant
              suggestions={[
                'Who needs a check today?',
                'Summarize everyone’s recent trends.',
                'Which residents are stable?',
              ]}
            />
          </details>
        </>
      )}
    </main>
  )
}
