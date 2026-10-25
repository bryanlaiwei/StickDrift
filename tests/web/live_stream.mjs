// The live stream sends about 60 samples a second whatever the screen's refresh rate, closes each game with
// whether it was played through, and never drops queued events to make room for samples.
import assert from 'node:assert/strict'
import { LiveStream } from '../../web/lobby/live.js'

const r3 = (v) => Math.round(v * 1e3) / 1e3 // measure.js rounds t to milliseconds
const sample = (t) => [t, ...new Array(16).fill(0)]
const opened = () => Object.assign(new LiveStream(), { token: 'test' })
const samples = (live) => live.queue.filter(Array.isArray)

let seed = 3
const noise = () => ((seed = (seed * 16807) % 2147483647) / 2147483647 - 0.5) * 2

for (const [hz, jitter] of [[60, 0], [60, 0.002], [120, 0], [120, 0.001], [144, 0], [144, 0.001]]) {
  const live = opened()
  const seconds = 10
  for (let i = 0; i < hz * seconds; i++) live.sample(sample(r3(0.1234 + i / hz + jitter * noise())))
  const times = samples(live).map((item) => item[0])
  const rate = times.length / seconds
  if (hz === 60) assert.equal(times.length, hz * seconds, `60 Hz keeps every frame (jitter ${jitter})`)
  else assert.ok(Math.abs(rate - 60) <= 0.5, `${hz} Hz -> ${rate}/s`)
  for (let s = 1; s < seconds - 1; s++) { // steady through the run, no drift
    const n = times.filter((t) => t >= 0.1234 + s && t < 0.1234 + s + 1).length
    assert.ok(n >= 59 && n <= 61, `${hz} Hz second ${s}: ${n}`)
  }
}

// after a stall the stream starts again from now instead of sending a burst to catch up
{
  const live = opened()
  for (let i = 0; i < 144; i++) live.sample(sample(r3(i / 144)))
  for (let i = 0; i < 144; i++) live.sample(sample(r3(3 + i / 144)))
  const late = samples(live).filter((item) => item[0] >= 3)
  assert.ok(Math.abs(late.length - 60) <= 1, `after a stall: ${late.length}`)
}

// level_end.completed says whether the game sent its result before the player left
{
  const live = opened()
  live.enter('lobby')
  live.enter('apple') // left early: no result
  live.enter('lobby')
  live.enter('rat')
  live.event('result', { score: 300 })
  live.enter('lobby')
  live.enter('fish')
  live.enter('lobby')
  const ends = live.queue.filter((e) => e.type === 'level_end').map((e) => [e.level, e.completed])
  assert.deepEqual(ends, [['lobby', false], ['apple', false], ['lobby', false], ['rat', true], ['lobby', false], ['fish', false]])
}

// a full queue drops the oldest samples, never the events between them
{
  const live = opened()
  live.event('level_start', { level: 'rat' })
  for (let i = 0; i < 60 * 30; i++) {
    live.sample(sample(r3(i / 60)))
    if (i === 100) live.event('slam', { hand: 'left' })
  }
  assert.equal(samples(live).length, 60 * 20)
  assert.deepEqual(live.queue.filter((e) => !Array.isArray(e)).map((e) => e.type), ['level_start', 'slam'])
  assert.equal(samples(live)[0][0], r3((60 * 30 - 60 * 20) / 60), 'the newest samples are kept')
}

// a failed post puts its items back without losing events
{
  const live = opened()
  globalThis.fetch = async () => { throw new Error('offline') }
  live.event('level_start', { level: 'apple' })
  for (let i = 0; i < 60 * 25; i++) live.sample(sample(r3(i / 60)))
  await live.flush()
  live.event('result', { score: 100 })
  for (let i = 0; i < 60; i++) live.sample(sample(r3(25 + i / 60)))
  assert.equal(samples(live).length, 60 * 20)
  assert.deepEqual(live.queue.filter((e) => !Array.isArray(e)).map((e) => e.type), ['level_start', 'result'])
}

console.log('live stream ok')
