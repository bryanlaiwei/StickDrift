// Reads the running lobby game's state each frame and turns it into what the caregiver's live view needs:
// where each in-game hand is, where the game wants it (both in -1..1, y down like the controller), and one
// measurement per attempt (an apple picked, a rat slammed). Read-only: it never changes the games.
//
// The games move a hand with the stick (velocity control), so "distance from target" is the in-game hand
// against the target, while shake and speed are read from the stick itself.

const ONSET = 0.25 // stick clearly pushed
const TOWARD = 0.7 // cos of the angle between the stick and the way to the target (about 45 degrees)
const HANDS = ['left', 'right']

const r4 = (v) => (v == null ? null : Math.round(v * 1e4) / 1e4)
const r3 = (v) => (v == null ? null : Math.round(v * 1e3) / 1e3)
const mag = (x, y) => Math.hypot(x, y)

/** One open reach: target appeared at t0, until the hand gets there (or the game moves on). */
class Reach {
  constructor(t0) {
    this.t0 = t0
    this.onset = null
    this.ready = false // reaction only counts once the stick was not already heading there
    this.peakSpeed = 0
    this.speed = 0
    this.peakPush = 0
    this.prev = null
  }

  /** stick = [x, y] (y down); toward = unit vector from the hand to the target in the same axes, or null. */
  update(t, stick, toward) {
    const m = mag(...stick)
    if (this.prev) {
      const dt = t - this.prev[0]
      if (dt > 0) {
        this.speed = 0.7 * this.speed + 0.3 * (mag(stick[0] - this.prev[1], stick[1] - this.prev[2]) / dt)
        this.peakSpeed = Math.max(this.peakSpeed, this.speed)
      }
    }
    this.prev = [t, ...stick]
    this.peakPush = Math.max(this.peakPush, Math.min(m, 1))
    const aimed = m > ONSET && (!toward || (stick[0] * toward[0] + stick[1] * toward[1]) / m > TOWARD)
    if (!aimed) this.ready = true
    else if (this.onset == null && this.ready) this.onset = t - this.t0
  }

  result(t, reached) {
    return {
      reaction_s: r3(this.onset),
      reach_s: reached ? r3(t - this.t0) : null,
      peak_speed: Math.round(this.peakSpeed * 100) / 100,
      reach_size: r3(this.peakPush),
      reached,
    }
  }
}

// ---- Apple Picking: red glove = left stick, blue glove = right stick --------------------------------
const APPLE_SCALE = 5.2, APPLE_CZ = 3.025 // hand area x -5.2..5.2, z 0.45..5.6
const appleXY = (x, z) => [x / APPLE_SCALE, -(z - APPLE_CZ) / APPLE_SCALE]
const BASKET_HAND = appleXY(0, 1.2) // where a carried apple drops in
const GLOVE = { left: 'red', right: 'blue' }

class AppleWatch {
  constructor() {
    this.open = { left: null, right: null }
    this.count = { left: 0, right: 0 }
    this.prevWrong = { red: 0, blue: 0 }
    this.prevScore = { red: 0, blue: 0 }
    this.seen = new Map()
    this.reported = false
  }

  frame(g, t, sticks, emit) {
    const out = { phase: null, trial: null, cur: [null, null], tgt: [null, null], on: [0, 0] }
    if (g.phase !== 'play' && g.phase !== 'done') return out
    HANDS.forEach((h, i) => {
      const c = GLOVE[h]
      const [hx, hz] = g.pos[c]
      const cur = appleXY(hx, hz)
      out.cur[i] = cur
      if (g.phase === 'done') {
        if (this.open[h]) emit(this.close(h, t, false))
        return
      }
      if (g.carry[c]) {
        if (this.open[h]) emit(this.close(h, t, true))
        out.tgt[i] = BASKET_HAND
        out.on[i] = 1
        out.phase = out.phase || 'carry'
        return
      }
      // nearest apple of this glove's colour, in the same spot the game checks for a pick
      let best = null, bestD = Infinity
      for (const a of g.apples) {
        if (a.state !== 'hang' || a.color !== c) continue
        const d = mag(a.x - hx, a.z - 0.5 - hz)
        if (d < bestD) { best = a; bestD = d }
      }
      if (!best) { // its apple fell away before it was picked
        if (this.open[h]) emit(this.close(h, t, false))
        return
      }
      const tgt = appleXY(best.x, best.z - 0.5)
      out.tgt[i] = tgt
      out.phase = 'cue'
      if (!this.open[h]) {
        this.count[h]++
        this.open[h] = new Reach(t)
      }
      const dx = tgt[0] - cur[0], dy = tgt[1] - cur[1], d = mag(dx, dy) || 1
      this.open[h].update(t, sticks[i], [dx / d, dy / d])
      out.trial = this.count[h]
    })
    this.marks(g, t, emit)
    return out
  }

  close(h, t, reached) {
    const e = { type: 'trial', t, trial: this.count[h], hand: h, ...this.open[h].result(t, reached) }
    this.open[h] = null
    return e
  }

  /** Facts the stick samples cannot reconstruct: a wrong colour, a basket drop, an apple that fell away. */
  marks(g, t, emit) {
    for (const [color, hand] of [['red', 'left'], ['blue', 'right']]) {
      for (; this.prevWrong[color] < g.wrongBy[color]; this.prevWrong[color]++) emit({ type: 'wrong', hand, t })
      const gained = g.score[color] - this.prevScore[color]
      for (let n = 0; n < gained; n++) emit({ type: 'basket', hand, t })
      this.prevScore[color] = g.score[color]
    }
    const alive = new Set(g.apples)
    for (const apple of g.apples) {
      const prev = this.seen.get(apple)
      if (prev === 'hang' && (apple.state === 'gone' || apple.state === 'dead')) {
        emit({ type: 'expired', hand: apple.color === 'red' ? 'left' : 'right', t })
      }
      this.seen.set(apple, apple.state)
    }
    for (const apple of this.seen.keys()) if (!alive.has(apple)) this.seen.delete(apple)
    // like the game, wait for the last apples to land in the basket so the score is final
    if (g.phase === 'done' && !this.reported && !g.apples.some((a) => a.state === 'fall')) {
      this.reported = true
      emit({
        type: 'result', t, score: g.points(), stars: g.stars(),
        red: g.score.red, blue: g.score.blue, wrong: g.wrong,
      })
    }
  }
}

// ---- Harbour Fishing: one hand at a time traces a lane ---------------------------------------------
const WATER_SCALE = 4.8, LANE_HALF = 0.5
const LANE_CY = 1.65 // fish.js draws the lane centred this far up the water
const waterXY = (p) => [p[0] / WATER_SCALE, -(p[1] - LANE_CY) / WATER_SCALE]

class FishWatch {
  constructor() {
    this.traces = 0
    this.reported = false
  }

  frame(g, t, _sticks, emit) {
    const out = { phase: null, trial: null, cur: [null, null], tgt: [null, null], on: [0, 0] }
    while (this.traces < g.stats.length) {
      const trace = g.stats[this.traces++]
      emit({
        type: 'trace', t, round: trace.round, hand: trace.side, shape: trace.shape,
        time_s: trace.time, on_lane_pct: trace.pct, off_count: trace.off, score: trace.score,
      })
    }
    if (g.state === 'done' && !this.reported) {
      this.reported = true
      emit({ type: 'result', t, score: g.points(), stars: g.stars(), caught: g.caught })
    }
    if (g.state !== 'trace') return out
    const i = g.side === 'left' ? 0 : 1
    const n = g.pts.length
    let best = g.pts[Math.min(g.prog, n - 1)], bestD = Infinity
    for (let k = Math.max(0, g.prog - 5); k < Math.min(n, g.prog + 14); k++) { // the stretch the game checks
      const d = mag(g.pts[k][0] - g.cur[0], g.pts[k][1] - g.cur[1])
      if (d < bestD) { best = g.pts[k]; bestD = d }
    }
    out.phase = 'track'
    out.trial = g.round + 1
    out.cur[i] = waterXY(g.cur)
    out.tgt[i] = waterXY(best)
    out.on[i] = bestD <= LANE_HALF ? 1 : 0
    return out
  }
}

// ---- Rat Catching: flick a stick up as the target rat passes under the hand ------------------------
/** One stick's upward pushes, followed all game, so each slam carries the timing of the flick that made it. */
class Flick {
  constructor() {
    this.prev = null
    this.speed = 0
    this.onset = null // when the current push went past ONSET
    this.peak = 0 // fastest the stick moved during the current push
  }

  update(t, up) {
    if (this.prev) {
      const dt = t - this.prev[0]
      if (dt > 0) this.speed = 0.7 * this.speed + 0.3 * (Math.abs(up - this.prev[1]) / dt)
      if (up > ONSET && this.prev[1] <= ONSET) {
        this.onset = t
        this.peak = 0
      }
    }
    if (up > ONSET) this.peak = Math.max(this.peak, this.speed)
    this.prev = [t, up]
  }
}

class RatWatch {
  constructor() {
    this.reach = null
    this.first = null // the run's first slam, which its trial event describes
    this.caught = false
    this.lastRun = null
    this.count = 0
    this.prev = { caught: 0, missed: 0, wrong: 0, empty: 0 }
    this.flicks = { left: new Flick(), right: new Flick() }
    this.lastSticks = null // the sticks on the frame before, which the game read when it flicked
    this.hs = null
    this.slam = null // the slam on its way down, until its outcome shows in the game's stats
    this.runRound = null
    this.reported = false
    this.seenRats = 0
  }

  frame(g, t, sticks, emit) {
    const out = { phase: g.state === 'run' ? 'run' : null, trial: null, cur: [null, null], tgt: [null, null], on: [0, 0] }
    const target = g.targets?.[g.round]
    const runKey = g.state === 'run' && g.rat === target ? `${g.round}-${g.runI}` : null
    if (runKey && runKey !== this.lastRun) { // a target rat just came out of the hole
      this.finish(t, emit)
      this.lastRun = runKey
      this.count++
      this.reach = { left: new Reach(t), right: new Reach(t) }
    }
    if (g.state === 'run') this.runRound = g.round + 1 // the game moves to the next round before a miss shows
    // only upward pushes count; y is down, so up is -y
    HANDS.forEach((h, i) => this.flicks[h].update(t, Math.max(0, -sticks[i][1])))
    if (g.hs === 'down' && this.hs !== 'down') {
      this.slam = this.startSlam(g, t, sticks)
      if (this.reach && !this.first) this.first = this.slam
    }
    this.hs = g.hs
    this.lastSticks = sticks
    if (this.reach) {
      out.trial = this.count
      HANDS.forEach((h, i) => this.reach[h].update(t, [0, Math.min(0, sticks[i][1])], [0, -1]))
      if (g.caughtThis) this.caught = true
      if (!runKey && g.hs !== 'down') this.finish(t, emit) // the rat is gone and the slam has landed
    }
    if (g.timed) {
      while (this.seenRats < g.timed.length) {
        const row = g.timed[this.seenRats++]
        emit({ type: 'card_rat', t, round: row.round, caught: row.caught, reaction_s: row.reaction_s })
      }
    }
    this.outcomes(g, t, emit)
    return out
  }

  /** The game just started a slam: credit the stick pushed up furthest, with that flick's own timing. */
  startSlam(g, t, sticks) {
    const seen = this.lastSticks || sticks
    const i = -seen[0][1] >= -seen[1][1] ? 0 : 1
    const hand = HANDS[i], flick = this.flicks[hand]
    const t0 = this.reach ? this.reach[hand].t0 : null // only a card rat on the run gives something to react to
    return {
      hand, t, round: g.round + 1,
      reaction_s: t0 != null && flick.onset != null && flick.onset > t0 ? r3(flick.onset - t0) : null,
      flick_speed: r3(flick.peak),
      other_stick: mag(...seen[1 - i]) > 0.25,
    }
  }

  outcomes(g, t, emit) {
    const stats = g.stats
    for (const outcome of ['caught', 'wrong', 'empty']) {
      while (this.prev[outcome] < stats[outcome]) {
        this.prev[outcome]++
        const slam = this.slam || { hand: null, round: g.round + 1, reaction_s: null, flick_speed: null, other_stick: false }
        this.slam = null
        emit({
          type: 'slam', t, hand: slam.hand, outcome, round: slam.round,
          reaction_s: slam.reaction_s,
          flick_speed: slam.flick_speed,
          early: outcome === 'empty',
          other_stick: slam.other_stick,
        })
      }
    }
    while (this.prev.missed < stats.missed) {
      this.prev.missed++
      emit({ type: 'miss', t, round: this.runRound ?? g.round + 1 })
    }
    if (g.state === 'done' && !this.reported) {
      this.reported = true
      const timing = g.timingReport ? g.timingReport() : null
      emit({
        type: 'result', t, score: g.points(), stars: g.stars(),
        caught: stats.caught, missed: stats.missed, wrong: stats.wrong, empty: stats.empty,
        target_rats: timing ? timing.target_rats : null,
        correctness_pct: timing ? timing.correctness_pct : null,
        median_reaction_s: timing ? timing.median_reaction_s : null,
      })
    }
  }

  finish(t, emit) {
    if (!this.reach) return
    const slam = this.first
    if (slam) {
      const res = this.reach[slam.hand].result(slam.t, this.caught)
      res.reach_s = r3(slam.t - this.reach[slam.hand].t0) // time to the slam, caught or not
      emit({ type: 'trial', trial: this.count, hand: slam.hand, ...res })
    }
    this.reach = null
    this.first = null
    this.caught = false
  }
}

const WATCHERS = { apple: AppleWatch, fish: FishWatch, rat: RatWatch }

export class Measure {
  constructor() {
    this.watch = null
  }

  /** Call when a game starts (name) or the player returns to the lobby (null). */
  enter(game) {
    this.watch = game && WATCHERS[game] ? new WATCHERS[game]() : null
  }

  /**
   * raw = [lx, ly, rx, ry] with y up (as input.js gives it). Returns the 17-value live sample and calls
   * emit(event) for finished attempts.
   */
  frame(game, t, raw, emit) {
    const sticks = [[raw[0], -raw[1]], [raw[2], -raw[3]]] // y down, like the controller and the garden
    const f = this.watch && game ? this.watch.frame(game, t, sticks, emit) : null
    const xy = (p) => (p ? [r4(p[0]), r4(p[1])] : [null, null])
    return [
      r3(t), f?.trial ?? null, f?.phase ?? null,
      r4(sticks[0][0]), r4(sticks[0][1]), r4(sticks[1][0]), r4(sticks[1][1]),
      ...xy(f?.tgt[0]), ...xy(f?.tgt[1]),
      f?.on[0] ?? 0, f?.on[1] ?? 0,
      ...xy(f?.cur[0]), ...xy(f?.cur[1]),
    ]
  }
}
