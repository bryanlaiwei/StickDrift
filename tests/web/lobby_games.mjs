// The lobby watcher, driven by the real Apple Picking and Rat Catching games, credits each attempt to the
// hand that made it.
import assert from 'node:assert/strict'

globalThis.window = { addEventListener() {} }
globalThis.document = { addEventListener() {}, hidden: false }
globalThis.localStorage = { getItem() { return null }, setItem() {} }

const { AppleGame } = await import('../../web/lobby/apple.js')
const { RatGame } = await import('../../web/lobby/rat.js')
const { Measure } = await import('../../web/lobby/measure.js')

const DT = 1 / 60
let seed = 7
Math.random = () => ((seed = (seed * 16807) % 2147483647) - 1) / 2147483646 // same rats and apples every run

/** Steps one game from the start, asking policy(game) each frame for the raw sticks [lx, ly, rx, ry] (y up). */
function play(game, name, policy, frames = 60 * 60) {
  const measure = new Measure()
  measure.enter(name)
  const events = []
  let t = 0
  for (let i = 0; i < frames; i++) {
    const raw = policy(game, t)
    measure.frame(game, t, raw, (e) => events.push(e))
    const pad = { move: [raw[0], raw[1], Math.hypot(raw[0], raw[1]) ? 1 : 0], look: [raw[2], raw[3]], back: false }
    if (game.update(DT, pad)) break
    t += DT
  }
  return events
}

const of = (events, type, outcome) => events.filter((e) => e.type === type && (!outcome || e.outcome === outcome))

// ---- Apple Picking: a wrong-colour touch names the glove that touched ---------------------------------------
for (const [glove, other, hand] of [['red', 'blue', 'left'], ['blue', 'red', 'right']]) {
  const game = new AppleGame()
  game.start()
  game.update(3.01, { move: [0, 0, 0], look: [0, 0], back: false }) // past the countdown
  game.nextSpawn = 1e9
  const [x, z] = game.pos[glove]
  const ob = game.free[other].pop()
  game.apples.push({ ob, color: other, state: 'hang', born: game.t, x, y: 0, z: z + 0.5, vz: 0, wob: -9, s: 1, tx: 0, ty: 0, rest: 0 })
  const events = play(game, 'apple', () => [0, 0, 0, 0], 3)
  assert.equal(game.wrong, 1)
  assert.deepEqual(of(events, 'wrong').map((e) => e.hand), [hand], `${glove} glove touched a ${other} apple`)
}

// ---- Apple Picking: the result waits for apples still falling into the basket -------------------------------
{
  const game = new AppleGame()
  game.start()
  game.update(3.01, { move: [0, 0, 0], look: [0, 0], back: false })
  game.nextSpawn = 1e9
  game.t = 15 - 2 * DT // two frames left on the clock
  game.pos.red = [0, 1.5] // over the basket
  const ob = game.free.red.pop()
  const apple = { ob, color: 'red', state: 'carried', born: game.t, x: 0, y: 0, z: 2, vz: 0, wob: -9, s: 1, tx: 0, ty: 0, rest: 0 }
  game.apples.push(apple)
  game.carry.red = apple
  const events = play(game, 'apple', () => [0, 0, 0, 0], 120)
  const results = of(events, 'result')
  assert.equal(results.length, 1)
  assert.equal(game.score.red, 1, 'the apple landed after the clock ran out')
  assert.equal(results[0].red, 1)
  assert.equal(results[0].score, game.points())
}

// ---- Rat Catching -----------------------------------------------------------------------------------------
const UP = { left: [0, 1, 0, 0], right: [0, 0, 0, 1], none: [0, 0, 0, 0] }
const isTarget = (g) => g.state === 'run' && g.rat === g.targets[g.round]
const underHand = (g) => g.state === 'run' && g.ratX < 1.0 && g.ratX > 0 // the slam lands about 0.1 s later

// one stick catches every card rat, the other slams every other rat
for (const [catcher, wronger] of [['left', 'right'], ['right', 'left']]) {
  const game = new RatGame()
  const events = play(game, 'rat', (g) => (underHand(g) ? UP[isTarget(g) ? catcher : wronger] : UP.none))
  const caught = of(events, 'slam', 'caught'), wrong = of(events, 'slam', 'wrong')
  assert.equal(caught.length, 6, `${catcher} catches all six card rats`)
  assert.ok(wrong.length >= 5, `${wronger} slams the other rats (${wrong.length})`)
  assert.equal(of(events, 'slam').length, caught.length + wrong.length)
  for (const e of caught) {
    assert.equal(e.hand, catcher)
    assert.ok(e.reaction_s > 0 && e.reaction_s < 1.5, `caught reaction ${e.reaction_s}`)
    assert.ok(e.flick_speed > 0)
    assert.equal(e.other_stick, false)
  }
  for (const e of wrong) {
    assert.equal(e.hand, wronger)
    assert.equal(e.reaction_s, null, 'no card rat was out, so there is nothing to react to')
  }
  assert.deepEqual(caught.map((e) => e.round), [1, 1, 2, 2, 3, 3])
  const trials = of(events, 'trial')
  assert.equal(trials.length, 6)
  for (const e of trials) {
    assert.equal(e.hand, catcher)
    assert.equal(e.reached, true)
  }
  assert.equal(of(events, 'result')[0].caught, 6)
}

// empty slams between rats, left stick in round 1 and right stick after
{
  const game = new RatGame()
  const events = play(game, 'rat', (g) => (g.state === 'gap' && g.timer > 0.3 ? UP[g.round === 0 ? 'left' : 'right'] : UP.none))
  const empty = of(events, 'slam', 'empty')
  assert.ok(empty.length >= 6, `empty slams (${empty.length})`)
  assert.equal(of(events, 'slam').length, empty.length)
  for (const e of empty) {
    assert.equal(e.hand, e.round === 1 ? 'left' : 'right')
    assert.equal(e.early, true)
  }
  assert.ok(empty.some((e) => e.hand === 'left') && empty.some((e) => e.hand === 'right'))
}

// two slams in one run: right too early, then left catches it; each keeps its own hand and timing
{
  const game = new RatGame()
  let slow = null
  const events = play(game, 'rat', (g) => {
    if (!isTarget(g)) return UP.none
    if (slow !== `${g.round}-${g.runI}`) { // give this card rat the slowest speed so both slams fit in its run
      slow = `${g.round}-${g.runI}`
      g.ratV = 7.3008
    }
    if (g.ratX > 8.4 && g.ratX < 8.75) return UP.right
    return underHand(g) ? UP.left : UP.none
  })
  const slams = of(events, 'slam')
  assert.equal(slams.length, 12)
  for (let i = 0; i < slams.length; i += 2) {
    const [early, catcher] = [slams[i], slams[i + 1]]
    assert.equal(early.outcome, 'empty')
    assert.equal(early.hand, 'right')
    assert.equal(catcher.outcome, 'caught')
    assert.equal(catcher.hand, 'left')
    assert.ok(early.reaction_s > 0 && early.reaction_s < 0.15, `early reaction ${early.reaction_s}`)
    assert.ok(catcher.reaction_s > early.reaction_s + 0.8, `catch reaction ${catcher.reaction_s}`)
    assert.ok(catcher.t > early.t)
  }
  assert.equal(of(events, 'trial').length, 6) // one per card rat
}

// a card rat that runs past on the last run of a round is a miss in that round, never "round 4"
{
  seed = 11
  for (let n = 0; n < 5; n++) {
    const game = new RatGame()
    const events = play(game, 'rat', () => UP.none)
    const misses = of(events, 'miss').map((e) => e.round)
    const cards = of(events, 'card_rat').filter((e) => !e.caught).map((e) => e.round)
    assert.equal(misses.length, 6)
    assert.deepEqual(misses, cards)
    assert.ok(misses.every((r) => r >= 1 && r <= 3), `miss rounds ${misses}`)
  }
}

console.log('lobby games ok')
