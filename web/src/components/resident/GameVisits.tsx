import { Fragment, useState } from 'react'
import type { GameResult, Visit, HandLive, LobbyGame, RatReport } from '../../api'
import { formatDateTime, pct, secs } from '../../format'
import { HandReplay } from '../charts/HandReplay'
import { RatPoints } from '../charts/RatPoints'
import { VisitPatterns } from './VisitPatterns'

const GAME_NAMES: Record<LobbyGame, string> = {
  apple: 'Apple Picking',
  fish: 'Harbour Fishing',
  rat: 'Rat Catching',
}
const BLURB: Record<LobbyGame, string> = {
  apple: 'Each hand picks apples of its own colour and carries them to the basket.',
  fish: 'One hand at a time steers a lure along a glowing lane.',
  rat: 'Flick a stick up to slam the hand when the target rat runs underneath.',
}
const ORDER: LobbyGame[] = ['apple', 'fish', 'rat']
type State = 'done' | 'early' | 'none'

/** One measurement: how it reads, and (if it is a number that can change visit to visit) how to compare it. */
interface Row {
  label: string
  value: (h: HandLive) => string
  hint?: string
  /** A number to compare with the previous visit, with the words for it going down or up. */
  compare?: { num: (h: HandLive) => number | null; fmt: (d: number) => string; down: string; up: string; same: number }
}

const caught = (h: HandLive) => (h.apples_total ? `${h.apples_reached} of ${h.apples_total}` : '—')
const compareTime = (key: 'reach_s' | 'reaction_s'): Row['compare'] => ({
  num: (h) => h[key],
  fmt: (d) => `${Math.abs(d).toFixed(2)} s`,
  down: 'quicker',
  up: 'slower',
  same: 0.05,
})
const points = (d: number) => {
  const n = Math.round(Math.abs(d) * 100)
  return `${n} ${n === 1 ? 'point' : 'points'}`
}

const MAIN: Record<LobbyGame, Row[]> = {
  apple: [
    { label: 'Apples picked', value: caught },
    {
      label: 'Time to pick an apple',
      value: (h) => secs(h.reach_s),
      hint: 'From the apple being free to the glove grabbing it',
      compare: compareTime('reach_s'),
    },
  ],
  fish: [
    {
      label: 'Time on the lane',
      value: (h) => pct(h.on_target),
      hint: 'Share of each trace the lure stayed on the glowing lane',
      compare: { num: (h) => h.on_target, fmt: points, down: 'less', up: 'more', same: 0.02 },
    },
    {
      label: 'Distance from the lane',
      value: (h) => pct(h.tracking_error),
      hint: 'Average distance, as a share of the water. Lower is closer.',
      compare: { num: (h) => h.tracking_error, fmt: points, down: 'closer', up: 'further', same: 0.01 },
    },
  ],
  rat: [
    { label: 'Target rats caught', value: caught },
    {
      label: 'Time to slam',
      value: (h) => secs(h.reach_s),
      hint: 'From the target rat appearing to the flick',
      compare: compareTime('reach_s'),
    },
  ],
}

const MORE: Record<LobbyGame, Row[]> = {
  apple: [
    { label: 'Reaction time', value: (h) => secs(h.reaction_s), hint: 'Apple appears → stick pushed toward it', compare: compareTime('reaction_s') },
    { label: 'Peak speed', value: (h) => (h.peak_speed == null ? '—' : `${h.peak_speed.toFixed(1)} tilts/s`) },
  ],
  fish: [
    { label: 'Shake', value: (h) => (h.shake == null ? '—' : `${(h.shake * 100).toFixed(1)}%`), hint: 'Leftover wobble after the smooth path' },
    { label: 'Shake rhythm', value: (h) => (h.shake_hz ? `${h.shake_hz} Hz` : '—'), hint: 'How many times a second the wobble repeats' },
  ],
  rat: [{ label: 'Reaction time', value: (h) => secs(h.reaction_s), compare: compareTime('reaction_s') }],
}

function stateOf(v: Visit, g: LobbyGame): State {
  if (!v.games[g]) return 'none'
  return v.games_finished.includes(g) ? 'done' : 'early'
}

/** Short plain-language result for one game, for the card headline and the history table. */
function headline(v: Visit, g: LobbyGame): string | null {
  const r = v.games[g]
  if (!r) return null
  const { left: l, right: rt } = r.hands
  if (g === 'fish') {
    const on = [l.on_target, rt.on_target].filter((x): x is number => x != null)
    return on.length ? `On the lane ${pct(on.reduce((a, b) => a + b, 0) / on.length)} of the time` : 'Played'
  }
  if (g === 'rat') {
    const rep = v.visit?.games?.rat
    if (rep?.target_rats) {
      return `Caught ${Math.round(((rep.correctness_pct ?? 0) / 100) * rep.target_rats)} of ${rep.target_rats} target rats`
    }
  }
  const got = (l.apples_reached ?? 0) + (rt.apples_reached ?? 0)
  const total = (l.apples_total ?? 0) + (rt.apples_total ?? 0)
  if (!total) return 'Played'
  return g === 'apple' ? `Picked ${got} of ${total} apples` : `Caught ${got} of ${total} target rats`
}

function compareText(row: Row, hand: 'left' | 'right', cur: GameResult, prev: GameResult | null): string | null {
  const c = row.compare
  if (!c || !prev) return null
  const a = c.num(cur.hands[hand]), b = c.num(prev.hands[hand])
  if (a == null || b == null) return null
  const d = a - b
  if (Math.abs(d) < c.same) return 'same as last visit'
  return `${c.fmt(d)} ${d < 0 ? c.down : c.up} than last visit`
}

const list = (xs: string[]) => (xs.length <= 1 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`)

/** Which games were played, left early or not played, with a plain sentence saying so. */
function StatusStrip({ visit, name }: { visit: Visit; name: string }) {
  const states = ORDER.map((g) => [g, stateOf(visit, g)] as const)
  const live = visit.status === 'in_progress'
  const names = (s: State) => states.filter(([, x]) => x === s).map(([g]) => GAME_NAMES[g])
  const done = names('done'), early = names('early'), none = names('none')
  const played = done.length + early.length
  const all = done.length === ORDER.length

  return (
    <div className={`visit-status ${all ? 'visit-status-ok' : 'visit-status-part'}`} role="status">
      <ol className="visit-chips" aria-label="Games in this visit">
        {states.map(([g, s]) => (
          <li key={g} className={`visit-chip visit-chip-${s}`}>
            <span className="visit-chip-mark" aria-hidden>
              {s === 'done' ? '✓' : s === 'early' ? '◐' : '–'}
            </span>
            <span>
              <strong>{GAME_NAMES[g]}</strong>
              <small>{s === 'done' ? 'Played through' : s === 'early' ? 'Left early' : live ? 'Not played yet' : 'Not played'}</small>
            </span>
          </li>
        ))}
      </ol>
      <p>
        {all ? (
          <>Played all {ORDER.length} games.</>
        ) : (
          <>
            <strong>
              Played {played} of {ORDER.length} games{live ? ' so far' : ''}.
            </strong>{' '}
            {none.length > 0 && (
              <>
                {name} {live ? 'has not played' : 'did not play'} {list(none)} {live ? 'yet' : 'in this visit'}.{' '}
              </>
            )}
            {early.length > 0 && (
              <>
                {list(early)} {early.length === 1 ? 'was' : 'were'} left before the end, so those results cover only the part
                that was played.{' '}
              </>
            )}
            {live && <>Still in the lobby: results update as each game ends.</>}
          </>
        )}
      </p>
    </div>
  )
}

function Cell({ row, hand, cur, prev }: { row: Row; hand: 'left' | 'right'; cur: GameResult; prev: GameResult | null }) {
  const note = compareText(row, hand, cur, prev)
  return (
    <td className="num">
      {row.value(cur.hands[hand])}
      {note && <small className="delta-note">{note}</small>}
    </td>
  )
}

function MeasureTable({ rows, cur, prev }: { rows: Row[]; cur: GameResult; prev: GameResult | null }) {
  return (
    <table className="game-table">
      <thead>
        <tr>
          <th scope="col">
            <span className="sr-only">Measurement</span>
          </th>
          <th scope="col">
            <i style={{ background: 'var(--hand-left)' }} aria-hidden /> Left hand
          </th>
          <th scope="col">
            <i style={{ background: 'var(--hand-right)' }} aria-hidden /> Right hand
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.label}>
            <th scope="row" title={r.hint}>
              {r.label}
            </th>
            <Cell row={r} hand="left" cur={cur} prev={prev} />
            <Cell row={r} hand="right" cur={cur} prev={prev} />
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function GameCard({
  game, visit, prev, rat,
}: { game: LobbyGame; visit: Visit; prev: GameResult | null; rat?: RatReport | null }) {
  const result = visit.games[game]
  const state = stateOf(visit, game)
  if (!result) {
    return (
      <article className="game-card game-card-none">
        <h3>{GAME_NAMES[game]}</h3>
        <p className="muted">{visit.status === 'in_progress' ? 'Not played yet.' : 'Not played in this visit.'}</p>
      </article>
    )
  }
  return (
    <article className="game-card">
      <header>
        <h3>{GAME_NAMES[game]}</h3>
        {state === 'done' ? <span className="badge badge-good">Played through</span> : <span className="badge">Left early</span>}
      </header>
      {game === 'rat' && rat && <RatPoints rat={rat} labeled={false} />}
      <p className="game-headline">{headline(visit, game)}</p>
      <p className="game-blurb muted">{BLURB[game]}</p>
      <MeasureTable rows={MAIN[game]} cur={result} prev={prev} />
      {rat?.median_reaction_s != null && (
        <p className="game-note">Median {secs(rat.median_reaction_s)} from the rat’s nose reaching the hand to the slam.</p>
      )}
      <details className="game-more">
        <summary>More detail</summary>
        <MeasureTable rows={MORE[game]} cur={result} prev={prev} />
        <p className="hint">{Math.round(result.play_s)} s of play recorded.</p>
      </details>
      {state === 'early' && <p className="hint">Left before the end: these numbers cover only the part that was played.</p>}
    </article>
  )
}

export function GameVisits({ visits, name }: { visits: Visit[]; name: string }) {
  const [handsOpen, setHandsOpen] = useState<ReadonlySet<string>>(() => new Set())
  const toggleHands = (id: string) =>
    setHandsOpen((open) => {
      const next = new Set(open)
      if (!next.delete(id)) next.add(id)
      return next
    })

  if (visits.length === 0) {
    return (
      <section className="panel calm">
        <h2>No game visits yet</h2>
        <p className="muted">
          A visit appears here as soon as {name} finishes or leaves their first game in the lobby, even if they do not play the
          others.
        </p>
      </section>
    )
  }
  const latest = visits[0]
  // the same game in the most recent earlier visit, for "compared with last visit"
  const previous = (g: LobbyGame) => visits.slice(1).find((v) => v.games[g])?.games[g] ?? null

  return (
    <>
      <section className="panel">
        <h2>
          Latest visit <span className="muted section-sub">{formatDateTime(latest.started_at)}</span>
          {latest.is_synthetic && <span className="badge badge-synthetic">Keyboard input</span>}
        </h2>
        <StatusStrip visit={latest} name={name} />
        <div className="game-grid">
          {ORDER.map((g) => (
            <GameCard
              key={g}
              game={g}
              visit={latest}
              prev={previous(g)}
              rat={g === 'rat' ? latest.visit?.games?.rat : null}
            />
          ))}
        </div>
        {latest.has_hand_replay && (
          <HandReplay sessionId={latest.session_id} info={latest.hand_replay} name={name} />
        )}
        <div className="game-patterns">
          <h3>Pattern model</h3>
          <p className="muted">Apple Picking and Harbour Fishing, scored when the resident leaves the lobby.</p>
          <VisitPatterns visits={visits} />
        </div>
        <details className="game-more game-glossary">
          <summary>What these measurements mean</summary>
          <dl>
            {ORDER.filter((g) => latest.games[g]).flatMap((g) =>
              [...MAIN[g], ...MORE[g]]
                .filter((r) => r.hint)
                .map((r) => (
                  <div key={`${g}-${r.label}`}>
                    <dt>
                      {r.label} <span className="muted">· {GAME_NAMES[g]}</span>
                    </dt>
                    <dd>{r.hint}</dd>
                  </div>
                )),
            )}
          </dl>
        </details>
        <p className="hint">
          Lobby games are free play: each visit is shown on its own and does not set a baseline. Comparisons are with the
          previous visit that included the same game.
        </p>
      </section>

      <section className="panel">
        <h2>All visits</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">When</th>
                <th scope="col">Games played</th>
                {ORDER.map((g) => (
                  <th scope="col" key={g}>
                    {GAME_NAMES[g]}
                  </th>
                ))}
                <th scope="col">Input</th>
                <th scope="col">Hands</th>
              </tr>
            </thead>
            <tbody>
              {visits.map((v) => {
                const n = ORDER.filter((g) => v.games[g]).length
                const open = handsOpen.has(v.session_id)
                return (
                  <Fragment key={v.session_id}>
                    <tr>
                      <td>
                        {formatDateTime(v.started_at)}
                        {v.status === 'in_progress' && <span className="badge badge-live">Playing</span>}
                      </td>
                      <td className={n < ORDER.length ? 'partial' : ''}>
                        {n} of {ORDER.length}
                      </td>
                      {ORDER.map((g) => {
                        const s = stateOf(v, g)
                        return (
                          <td key={g} className={s === 'none' ? 'muted' : ''}>
                            {s === 'none' ? 'Not played' : headline(v, g)}
                            {s === 'early' && <small className="delta-note">left early</small>}
                            {g === 'rat' && v.visit?.games?.rat?.score != null && (
                              <small className="delta-note">{v.visit.games.rat.score} pts</small>
                            )}
                          </td>
                        )
                      })}
                      <td>
                        {v.is_synthetic ? (
                          <span className="badge badge-synthetic">Keyboard</span>
                        ) : (
                          <span className="muted">Controller</span>
                        )}
                      </td>
                      <td>
                        {v.has_hand_replay ? (
                          <button
                            type="button"
                            className="hand-toggle"
                            aria-expanded={open}
                            aria-controls={`hands-${v.session_id}`}
                            onClick={() => toggleHands(v.session_id)}
                          >
                            {open ? 'Hide' : 'Show'}
                            <span className="sr-only"> reconstructed hands for {formatDateTime(v.started_at)}</span>
                          </button>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                    </tr>
                    {open && (
                      <tr id={`hands-${v.session_id}`} className="hand-row">
                        <td colSpan={ORDER.length + 4}>
                          <HandReplay sessionId={v.session_id} info={v.hand_replay} name={name} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>
    </>
  )
}
