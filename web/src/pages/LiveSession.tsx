import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { type HandLive, type LiveStatus } from '../api'
import { HandReplay } from '../components/charts/HandReplay'
import { PatternBars } from '../components/charts/PatternBars'
import { RatPoints } from '../components/charts/RatPoints'
import { DiffBars } from '../components/live/DiffBars'
import { ReachTrialsChart } from '../components/live/ReachTrialsChart'
import { RollingChart } from '../components/live/RollingChart'
import { StickFields } from '../components/live/StickFields'
import { hasPatternScores, levelName } from '../labels'
import { handPoint, handPos, handTarget } from '../components/live/samples'
import { pct, secs } from '../format'
import { TabPanel, Tabs } from '../components/ui/Tabs'
import { useLiveFeed } from '../components/live/useLiveFeed'

const DONE: LiveStatus[] = ['finished', 'failed', 'lost', 'ended']

const STATUS_TEXT: Record<LiveStatus, string> = {
  ready: 'In the lobby',
  playing: 'Playing',
  scoring: 'Judging with the pattern model',
  finished: 'Session judged',
  failed: 'Could not judge',
  lost: 'Connection lost',
  ended: 'Session finished',
}

function elapsed(s: number) {
  const m = Math.floor(s / 60)
  return `${m}:${String(Math.floor(s % 60)).padStart(2, '0')}`
}

function Tile({ label, left, right, hint }: { label: string; left: string; right: string; hint?: string }) {
  return (
    <div className="tile">
      <span className="tile-label">{label}</span>
      <span className="tile-vals">
        <span>
          <i style={{ background: 'var(--hand-left)' }} aria-hidden /> <span className="sr-only">Left</span>
          {left}
        </span>
        <span>
          <i style={{ background: 'var(--hand-right)' }} aria-hidden /> <span className="sr-only">Right</span>
          {right}
        </span>
      </span>
      {hint && <span className="tile-hint">{hint}</span>}
    </div>
  )
}

function tiles(h: { left: HandLive; right: HandLive }) {
  const both = (f: (x: HandLive) => string) => [f(h.left), f(h.right)] as const
  const shake = (x: HandLive) => (x.shake == null ? '—' : `${(x.shake * 100).toFixed(1)}%${x.shake_hz ? ` · ${x.shake_hz} Hz` : ''}`)
  const change = (x: HandLive) =>
    x.speed_change_pct == null ? '—' : `${x.speed_change_pct > 0 ? '+' : ''}${x.speed_change_pct.toFixed(0)}%`
  return {
    speed: [
      {
        label: 'Reaction time',
        vals: both((x) => secs(x.reaction_s)),
        hint: 'Target appears → stick pushed toward it',
      },
      {
        label: 'Time to pick / slam',
        vals: both((x) => secs(x.reach_s)),
        hint: 'Apple Picking: until the glove grabs it · Rat Catching: until the flick',
      },
      { label: 'Peak speed', vals: both((x) => (x.peak_speed == null ? '—' : `${x.peak_speed.toFixed(1)} tilts/s`)) },
      { label: 'Stick push', vals: both((x) => pct(x.reach_size)), hint: 'How far the stick was pushed, at most' },
      {
        label: 'Speed, first → last tries',
        vals: both(change),
        hint: 'Negative = slowing down as it went on',
      },
      {
        label: 'Apples picked / rats caught',
        vals: both((x) => (x.apples_total ? `${x.apples_reached}/${x.apples_total}` : '—')),
      },
    ],
    steady: [
      {
        label: 'Distance from target',
        vals: both((x) => pct(x.tracking_error)),
        hint: 'Fishing lure to the lane, as a share of the water',
      },
      { label: 'Time on target', vals: both((x) => pct(x.on_target)) },
      { label: 'Shake', vals: both(shake), hint: 'Leftover wobble after the smooth path · rhythm' },
    ],
  }
}

export default function LiveSession() {
  const { id = '' } = useParams()
  const { snap, samples, error, mode } = useLiveFeed(id)
  const [chart, setChart] = useState<'distance' | 'tilt'>('distance')
  const [mTab, setMTab] = useState<'speed' | 'steady' | 'diff'>('speed')

  if (!snap) {
    return (
      <main className="wrap page-pad">
        <p className="crumb">
          <Link to="/caregiver">← All residents</Link>
        </p>
        {error ? (
          <p className="error" role="alert">
            {error}
          </p>
        ) : (
          <p className="muted">Connecting to the live session…</p>
        )}
      </main>
    )
  }

  const live = !DONE.includes(snap.status) && snap.status !== 'scoring'
  const t = tiles(snap.metrics.hands)
  const reachTrials = snap.metrics.reach_trials
  const judged = snap.status === 'scoring' || Boolean(snap.result) || snap.status === 'failed' || snap.status === 'lost'
  const replayReady = Boolean(snap.db_session_id && snap.hand_replay_ready)

  return (
    <main className="wrap page-pad">
      <p className="crumb">
        <Link to="/caregiver">← All residents</Link> ·{' '}
        <Link to={`/caregiver/residents/${snap.resident_id}`}>{snap.name}’s profile</Link>
      </p>

      <div className="page-head">
        <div>
          <p className="step">{live ? 'Live session' : 'Game session'}</p>
          <h1>
            {snap.name}{' '}
            <span className={`live-pill live-${snap.status}`}>
              {live && <span className="pulse" aria-hidden />}
              {STATUS_TEXT[snap.status]}
              {snap.status === 'playing' && snap.level ? ` · ${levelName(snap.level)}` : ''}
            </span>
          </h1>
          <p className="muted">
            {elapsed(snap.elapsed_s)} since opening
            {live && (
              <span className={`feed-mode feed-${mode}`} title={mode === 'polling' ? 'The live stream could not connect, so this page is checking every quarter second.' : undefined}>
                {mode === 'live' ? 'Streaming' : mode === 'polling' ? 'Refreshing' : 'Connecting…'}
              </span>
            )}
            {snap.synthetic && <span className="badge badge-synthetic">Keyboard / simulated input</span>}
          </p>
        </div>
      </div>

      <ol className="game-track" aria-label="Games">
        {snap.levels.filter((l) => l !== 'lobby').map((c) => {
          const state = snap.levels_done.includes(c) ? 'done' : snap.level === c ? 'now' : 'todo'
          return (
            <li key={c} className={`game-step game-step-${state}`}>
              <span className="game-step-dot" aria-hidden />
              {levelName(c)}
              <span className="sr-only"> ({state === 'done' ? 'finished' : state === 'now' ? 'in progress' : 'not started'})</span>
            </li>
          )
        })}
      </ol>

      {error && (
        <p className="error" role="alert">
          Connection hiccup: {error}
        </p>
      )}

      {(judged || replayReady || snap.hand_replay_pending) && (
        <section className={`panel judge ${snap.result ? 'judge-done' : ''}`} aria-live="polite">
          <h2>End-of-session judgement</h2>
          {snap.result ? (
            <>
              {hasPatternScores(snap.result.scores) && snap.result.scores && (
                <PatternBars scores={snap.result.scores} levels={snap.result.levels} />
              )}
              {snap.result.rat && <RatPoints rat={snap.result.rat} />}
              {snap.db_session_id && (
                <p className="muted">
                  Saved to {snap.name}’s record.{' '}
                  <Link to={`/caregiver/residents/${snap.resident_id}`}>Open profile</Link>
                </p>
              )}
            </>
          ) : snap.status === 'scoring' ? (
            <p className="muted">
              <span className="pulse" aria-hidden /> The TCN movement pattern model is reviewing the whole session…
            </p>
          ) : null}
          {replayReady ? (
            <HandReplay sessionId={snap.db_session_id} info={snap.hand_replay} name={snap.name} />
          ) : (
            snap.hand_replay_pending && <HandReplay pending />
          )}
          {judged && snap.error && <p className="error">{snap.error}</p>}
        </section>
      )}

      <section className="panel">
        <div className="panel-head">
          <h2>{live ? 'Right now' : 'Last moments'}</h2>
          <Tabs
            variant="pills"
            label="Live chart"
            value={chart}
            onChange={setChart}
            items={[
              { key: 'distance', label: 'Distance from target' },
              { key: 'tilt', label: 'Stick tilt' },
            ]}
          />
        </div>
        <div className="live-grid">
          <StickFields samples={samples} />
          {chart === 'distance' ? (
            <RollingChart
              title="Distance from target"
              caption={
                snap.level === 'rat'
                  ? 'Rat Catching is about timing, so it has no target to follow. See Stick tilt for the flicks.'
                  : 'How far the in-game hand or lure is from its target, as a share of the play area. Lower is closer.'
              }
              samples={samples}
              windowS={20}
              max={1}
              format={(v) => `${Math.round(v * 100)}%`}
              value={(s, h) => {
                const tg = handTarget(s, h)
                if (!tg) return null
                const [x, y] = handPoint(s, h)
                return Math.hypot(x - tg[0], y - tg[1])
              }}
            />
          ) : (
            <RollingChart
              title="Stick tilt"
              caption="How far each stick is pushed from the middle."
              samples={samples}
              windowS={20}
              max={1}
              format={(v) => `${Math.round(v * 100)}%`}
              value={(s, h) => Math.min(1, Math.hypot(...handPos(s, h)))}
            />
          )}
        </div>
        {samples.length === 0 && (
          <p className="muted">Movement appears here once the resident starts moving.</p>
        )}
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Measurements</h2>
          <Tabs
            variant="pills"
            label="Measurement group"
            value={mTab}
            onChange={setMTab}
            items={[
              { key: 'speed', label: 'Speed and size' },
              { key: 'steady', label: 'Steadiness' },
              { key: 'diff', label: 'Left vs right' },
            ]}
          />
        </div>
        <p className="muted key-line">
          <span className="key-inline"><i style={{ background: 'var(--hand-left)' }} /> Left</span>{' '}
          <span className="key-inline"><i style={{ background: 'var(--hand-right)' }} /> Right</span> · updates as they play
        </p>
        <TabPanel>
          {mTab === 'speed' && (
            <>
              <div className="tile-grid">
                {t.speed.map((x) => (
                  <Tile key={x.label} label={x.label} left={x.vals[0]} right={x.vals[1]} hint={x.hint} />
                ))}
              </div>
              <ReachTrialsChart trials={reachTrials} level={snap.level} />
            </>
          )}
          {mTab === 'steady' && (
            <div className="tile-grid">
              {t.steady.map((x) => (
                <Tile key={x.label} label={x.label} left={x.vals[0]} right={x.vals[1]} hint={x.hint} />
              ))}
            </div>
          )}
          {mTab === 'diff' && <DiffBars diff={snap.metrics.left_right_difference_pct} />}
        </TabPanel>
        <p className="hint">
          These describe movement during this session only. Comparing with earlier visits is what shows a real change.
        </p>
      </section>
    </main>
  )
}
