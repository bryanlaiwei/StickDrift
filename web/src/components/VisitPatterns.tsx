import type { Visit } from '../api'
import { formatDateTime } from '../format'
import { PatternBars, hasPatternScores } from './LiveCharts'

/** Why a lobby visit has no pattern scores, in words a caregiver can act on. */
function unscoredReason(v: Visit): string {
  if (v.status === 'in_progress') return 'The latest visit is still going. Its scores appear when the resident leaves the lobby.'
  if (!v.games.apple && !v.games.fish) {
    return 'The latest visit had no Apple Picking or Harbour Fishing, the two games the pattern model scores.'
  }
  if (v.tcn?.levels?.some((level) => level.error)) return 'The pattern model could not score the latest visit.'
  if (!v.tcn) return 'The latest visit was saved without pattern scores.'
  return 'The latest visit had too little movement for the pattern model to score.'
}

/**
 * The pattern chart for a resident's lobby visits (newest first). It is always drawn: from the latest visit
 * when that was scored, otherwise from the most recent scored visit, otherwise empty, with a note saying why.
 */
export function VisitPatterns({ visits }: { visits: Visit[] }) {
  const latest = visits[0]
  const shown = visits.find((v) => hasPatternScores(v.tcn?.scores))
  return (
    <>
      {latest && shown !== latest && (
        <p className="pattern-note">
          {unscoredReason(latest)}{' '}
          {shown
            ? `Showing the most recent scored visit, ${formatDateTime(shown.started_at)}.`
            : 'No visit has been scored yet.'}
        </p>
      )}
      <PatternBars scores={shown?.tcn?.scores ?? {}} levels={shown?.tcn?.levels} />
    </>
  )
}
