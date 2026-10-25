import type { Concern, Insights, Risk } from '../api'

const RISK_LABEL: Record<Risk, string> = {
  check: 'Check soon',
  watch: 'Keep an eye on',
  none: 'No concerns',
}

export function RiskBadge({ risk }: { risk: Risk }) {
  return <span className={`risk-badge risk-${risk}`}>{RISK_LABEL[risk]}</span>
}

/** One-strip status at the top of a resident page. `onSeeDetails` jumps to the concerns. */
export function RiskAlert({
  name,
  insights,
  onSeeDetails,
}: {
  name: string
  insights: Insights
  onSeeDetails?: () => void
}) {
  if (insights.status !== 'ok' && insights.concerns.length === 0) {
    return (
      <div className="risk-alert risk-alert-none" role="status">
        <div className="risk-alert-body">
          <strong>
            {insights.visit_count ? 'Game visits recorded' : 'Building a baseline'}
          </strong>
          <p>{insights.summary}</p>
        </div>
      </div>
    )
  }
  if (insights.risk === 'none') {
    return (
      <div className="risk-alert risk-alert-none" role="status">
        <div className="risk-alert-body">
          <strong>Nothing to flag</strong>
          <p>{name}’s recent sessions are in line with their usual pattern.</p>
        </div>
      </div>
    )
  }
  return (
    <div className={`risk-alert risk-alert-${insights.risk}`} role="alert">
      <svg viewBox="0 0 24 24" aria-hidden className="risk-icon">
        <path d="M12 3 2 21h20L12 3Z" />
        <path d="M12 10v5M12 18v.01" />
      </svg>
      <div className="risk-alert-body">
        <strong>
          {insights.risk === 'check' ? 'Worth checking in' : 'Worth keeping an eye on'}
        </strong>
        <p>
          {insights.concerns.map((c) => c.title).join(' · ')}
        </p>
      </div>
      {onSeeDetails && (
        <button type="button" className="btn btn-small btn-quiet" onClick={onSeeDetails}>
          What to check
        </button>
      )}
    </div>
  )
}

export function ConcernCard({ concern }: { concern: Concern }) {
  // Comparison rows ("Unchanged for comparison…") are context, not evidence of a change.
  const changed = concern.evidence.filter((e) => !e.startsWith('Unchanged for comparison'))
  const steady = concern.evidence.filter((e) => e.startsWith('Unchanged for comparison'))
  const checks = concern.recommended_checks
  return (
    <article className={`concern concern-${concern.level}`}>
      <header>
        <h3>{concern.title}</h3>
        <span className={`risk-badge risk-${concern.level}`}>{RISK_LABEL[concern.level]}</span>
      </header>
      <p className="concern-summary">{concern.summary}</p>

      <div className="concern-cols">
        <section>
          <h4>What changed</h4>
          <ul>
            {changed.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
          {steady.length > 0 && (
            <p className="muted concern-steady">
              {steady.map((s) => s.replace('Unchanged for comparison - ', '')).join(' ')}
            </p>
          )}
        </section>
        <section className="concern-checks">
          <h4>What to check</h4>
          <ol>
            {checks.slice(0, 3).map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ol>
          {checks.length > 3 && (
            <details>
              <summary>{checks.length - 3} more</summary>
              <ol start={4}>
                {checks.slice(3).map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ol>
            </details>
          )}
        </section>
      </div>

      <div className="concern-more">
        <details>
          <summary>Possible reasons</summary>
          <ul>
            {concern.possible_contributors.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </details>
        <details>
          <summary>Research basis</summary>
          <ul>
            {concern.references.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </details>
      </div>
    </article>
  )
}
