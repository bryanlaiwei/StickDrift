// The lobby watcher emits the short event list the visit report stores.
import assert from 'node:assert/strict'
import { Measure } from '../../web/lobby/measure.js'

const events = []
const emit = (event) => events.push(event)
const measure = new Measure()

measure.enter('apple')
const apple = {
  phase: 'play',
  wrong: 0,
  wrongBy: { red: 0, blue: 0 },
  score: { red: 0, blue: 0 },
  apples: [],
  carry: { red: null, blue: null },
  pos: { red: [0, 1], blue: [0, 1] },
  points() { return this.score.red * 100 },
  stars() { return 0 },
}
measure.frame(apple, 1, [0, 0, 0, 0], emit)
apple.wrong = 1
apple.wrongBy.red = 1 // the red glove (left stick) touched a blue apple
apple.apples.push({ color: 'blue', state: 'hang', wob: 5, x: 0, z: 4 })
measure.frame(apple, 2, [0, 0, 0, 0], emit)
apple.apples[0].state = 'gone'
measure.frame(apple, 3, [0, 0, 0, 0], emit)
apple.score.red = 1
apple.phase = 'done'
measure.frame(apple, 4, [0, 0, 0, 0], emit)

assert.deepEqual(events.map((event) => event.type), ['wrong', 'trial', 'expired', 'basket', 'result'])
assert.equal(events[0].hand, 'left')
assert.equal(events[1].reached, false)
assert.equal(events[2].hand, 'right')
assert.equal(events[3].hand, 'left')
assert.equal(events[4].score, 100)

events.length = 0
measure.enter('fish')
const fish = {
  state: 'intro', stats: [], side: 'left', pts: [[0, 0]], prog: 0, cur: [0, 0], round: 0, caught: 1,
  points() { return 500 }, stars() { return 2 },
}
measure.frame(fish, 0, [0, 0, 0, 0], emit)
fish.stats.push({ round: 1, side: 'left', shape: 'wave', time: 8, pct: 80, off: 2, score: 500 })
fish.state = 'done'
measure.frame(fish, 1, [0, 0, 0, 0], emit)
assert.equal(events[0].type, 'trace')
assert.equal(events[0].shape, 'wave')
assert.equal(events[0].on_lane_pct, 80)
assert.equal(events[1].type, 'result')

events.length = 0
measure.enter('rat')
const rat = {
  state: 'done', round: 2, targets: ['grey', 'white', 'ginger'], runI: 0, rat: null, hs: 'idle', caughtThis: false,
  stats: { caught: 1, missed: 1, wrong: 0, empty: 1 },
  points() { return 250 }, stars() { return 1 },
}
measure.frame(rat, 1, [0, 0, 0, -1], emit)
assert.equal(events.filter((event) => event.type === 'slam' && event.outcome === 'caught').length, 1)
assert.equal(events.filter((event) => event.type === 'miss').length, 1)
assert.equal(events.at(-1).type, 'result')
assert.equal(events.at(-1).empty, 1)

console.log('lobby measure events ok')
