// Live stream of the lobby to the Stick Drift API, so a caregiver can watch on the dashboard.
// Uses the resident's login cookie to open a session, then posts stick samples and game
// changes to /live/ingest about ten times a second. It never blocks or breaks the game:
// with no login or no API it stays silent.
const API = '/api'
const SAMPLE_HZ = 60
const POST_EVERY_MS = 100
const MAX_QUEUE = SAMPLE_HZ * 20

/** Drop the oldest samples past MAX_QUEUE. Events (level changes, slams, results) are always kept. */
function trimSamples(queue) {
  let extra = queue.reduce((n, item) => n + Array.isArray(item), 0) - MAX_QUEUE
  return extra > 0 ? queue.filter((item) => !Array.isArray(item) || extra-- <= 0) : queue
}

export class LiveStream {
  constructor() {
    this.token = null
    this.queue = []
    this.level = null
    this.t0 = performance.now()
    this.nextSample = -Infinity
    this.finished = false // the current game sent its result
    this.sending = false
    this.ended = false
  }

  async start(keyboard, levels) {
    try {
      const res = await fetch(`${API}/me/lobby/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ keyboard }),
      })
      if (!res.ok) return false // not logged in as a resident: play without streaming
      this.token = (await res.json()).token
    } catch {
      return false
    }
    this.event('session_start', { levels, synthetic: keyboard })
    this.enter('lobby')
    this.timer = setInterval(() => this.flush(), POST_EVERY_MS)
    window.addEventListener('pagehide', () => this.end())
    return true
  }

  event(type, data = {}) {
    if (type === 'result') this.finished = true
    if (this.token) this.queue.push({ type, ...data })
  }

  /** Switch the stream to a game (or back to 'lobby'), closing the previous one. */
  enter(level) {
    if (this.level) this.event('level_end', { level: this.level, completed: this.level !== 'lobby' && this.finished })
    this.level = level
    this.finished = false
    this.event('level_start', { level })
  }

  /** Seconds since the stream opened; the clock the samples use. */
  now() {
    return (performance.now() - this.t0) / 1000
  }

  /** Tell the caregiver view once a controller is in use (the page only sees one after a button press). */
  source(src) {
    if (src === 'gamepad' && !this.sawPad && this.token) {
      this.sawPad = true
      this.event('input', { source: 'gamepad' })
    }
  }

  /** One 17-value sample from measure.js, plus gyro xyz and acc xyz when motion.latest() has them. */
  sample(item, motion) {
    if (!this.token) return
    // Each sample is due one period after the last was due, so a 60 Hz screen keeps every frame and a faster one
    // keeps about 60 a second. The half-period slack absorbs frame jitter and the millisecond rounding of t.
    const period = 1 / SAMPLE_HZ
    if (item[0] < this.nextSample - period / 2) return
    // after a stall, carry on from now instead of sending a burst to catch up
    this.nextSample = item[0] > this.nextSample + period ? item[0] + period : this.nextSample + period
    const sent = motion && motion.length >= 6 ? item.concat(motion.slice(0, 6)) : item
    this.queue.push(sent)
    if (this.queue.length > MAX_QUEUE) this.queue = trimSamples(this.queue)
  }

  async flush() {
    if (!this.token || this.sending || this.queue.length === 0) return
    const items = this.queue.splice(0, 2000)
    this.sending = true
    try {
      const res = await fetch(`${API}/live/ingest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Live-Token': this.token },
        body: JSON.stringify({ items }),
      })
      if (res.status === 410) this.stop() // the API forgot this session (restart or timeout)
    } catch {
      this.queue = trimSamples(items.concat(this.queue)) // best effort: keep recent samples for a retry
    } finally {
      this.sending = false
    }
  }

  stop() {
    clearInterval(this.timer)
    this.token = null
  }

  end() {
    if (!this.token || this.ended) return
    this.ended = true
    const token = this.token
    const items = this.queue.splice(0)
    const headers = { 'Content-Type': 'application/json', 'X-Live-Token': token }
    // One request, so the last samples (including the rat-game result) are scored with the visit.
    // keepalive lets it finish while the tab is closing.
    fetch(`${API}/live/end`, { method: 'POST', headers, body: JSON.stringify({ items }), keepalive: true }).catch(() => {})
    this.stop()
  }
}
