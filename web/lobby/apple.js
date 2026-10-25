// Game 1 - Apple Picking. First person: red glove = left stick, blue glove = right stick. Hover a matching
// apple to grab it, drag it over the basket and it drops in. 15 seconds. Port of the Blender version.
import * as THREE from 'three'
import { addSun } from './lights.js'
import { MAX_STARS, record } from './scores.js'
import { sfx } from './audio.js'
import { RETURN_DELAY, blob, box, clamp, cyl, makeHand, mat, mergeStatic, perspectiveCam, rng, setLens, sphere, torus, uniform, choice } from './util.js'

const APPLE_TIME = 15, COUNTDOWN = 3
const HAND_SPEED = 5.5, PICK_R = 0.85, HAND_Y = -0.6
const HAND_BOUNDS = [-5.2, 5.2, 0.45, 5.6] // x min/max, z min/max of the palm centre
const BASKET = [0, -0.5, 1.0]
const APPLE_AREA = [-4.5, 4.5, 3.4, 5.5]
const APPLE_LIFE = 6.5, POOL = 14
const COLORS = { red: [0.8, 0.02, 0.02], blue: [0.03, 0.12, 0.9] }
const HAND_START = { red: [-3.9, 0.9], blue: [3.9, 0.9] }
const names = ['red', 'blue']

function buildApple(color) {
  const g = new THREE.Group()
  sphere(g, 0.42, [0, 0, 0], mat(COLORS[color], { rough: 0.3 }), [1, 1, 0.92], 10)
  cyl(g, 0.03, 0.24, [0, 0, 0.42], mat([0.25, 0.15, 0.05]), 5)
  const leaf = sphere(g, 0.12, [0.12, 0, 0.5], mat([0.15, 0.55, 0.15]), [1, 0.35, 0.15], 6)
  leaf.rotation.y = -0.5
  g.visible = false
  return g
}

export class AppleGame {
  constructor() {
    this.scene = new THREE.Scene()
    this.scene.background = new THREE.Color().setRGB(0.45, 0.68, 0.95, THREE.LinearSRGBColorSpace)
    addSun(this.scene, { intensity: 6, fill: 1.8, extent: 14 })
    const st = new THREE.Group()
    this.scene.add(st)
    const grass = mat([0.25, 0.55, 0.2]), bark = mat([0.33, 0.2, 0.1], { rough: 0.95 })
    const leaf = [mat([0.1, 0.42, 0.13]), mat([0.15, 0.52, 0.17]), mat([0.22, 0.62, 0.2])]
    const wicker = mat([0.66, 0.45, 0.22], { rough: 0.9, side: THREE.DoubleSide }), dark = mat([0.36, 0.21, 0.09], { rough: 0.9 })
    box(st, [34, 34, 0.4], [0, 0, -0.2], grass)
    cyl(st, 0.6, 4.4, [0, 1.2, 2.2], bark, 10, 0.4)
    const r = rng(7)
    for (let k = 0; k < 26; k++) {
      const x = (r() * 2 - 1) * 6.5
      const z = 5.0 + (r() * 2.2 - 0.9) - Math.abs(x) * 0.08
      blob(st, 1.1 + r() * 0.6, [x, 1.2 + (r() * 0.8 - 0.2), z], leaf[k % 3], 0.85, k)
    }
    for (let k = 0; k < 7; k++) blob(st, 1.0 + r() * 0.6, [-9 + k * 3, 8, 0.5], leaf[k % 3], 0.7, 50 + k)
    // basket: open wicker bowl with woven bands, a rim and a dark floor
    const bowl = new THREE.CylinderGeometry(1.55, 1.0, 0.85, 24, 1, true)
    bowl.rotateX(Math.PI / 2)
    const bm = new THREE.Mesh(bowl, wicker)
    bm.position.set(BASKET[0], BASKET[1], 0.575)
    bm.castShadow = bm.receiveShadow = true
    this.scene.add(bm)
    cyl(this.scene, 0.95, 0.06, [BASKET[0], BASKET[1], 0.2], dark, 20)
    for (const [z, rad, m] of [[1.0, 1.55, wicker], [0.82, 1.45, dark], [0.58, 1.27, dark], [0.34, 1.1, dark]]) torus(this.scene, rad, 0.06, [BASKET[0], BASKET[1], z], m, 20, 4)
    mergeStatic(st)

    this.camera = perspectiveCam(28, 60)
    this.camera.position.set(0, -10, 5)
    const d = (10 * Math.PI) / 180
    this.camera.lookAt(0, -10 + 10 * Math.cos(d), 5 - 10 * Math.sin(d))

    this.hands = {}
    for (const c of names) {
      const h = makeHand(COLORS[c], { flip: c === 'blue' })
      this.scene.add(h.root)
      this.hands[c] = h
    }
    this.pool = { red: [], blue: [] }
    for (const c of names) for (let i = 0; i < POOL; i++) {
      const a = buildApple(c)
      this.scene.add(a)
      this.pool[c].push(a)
    }
    this.start()
  }

  resize(aspect) {
    setLens(this.camera, 28, aspect)
  }

  start() {
    this.t = -COUNTDOWN
    this.phase = 'countdown'
    this.score = { red: 0, blue: 0 }
    this.wrong = 0
    this.wrongBy = { red: 0, blue: 0 } // the glove that made each wrong touch
    this.rec = null
    this.lastCd = null
    this.pos = { red: [...HAND_START.red], blue: [...HAND_START.blue] }
    this.carry = { red: null, blue: null }
    this.apples = []
    this.inBasket = 0
    this.free = { red: [...this.pool.red], blue: [...this.pool.blue] }
    this.nextSpawn = 0.4
    this.lastColors = []
    for (const c of names) for (const ob of this.pool[c]) {
      ob.visible = false
      ob.scale.setScalar(0)
    }
    this.big = ''
    this.applyHands(0)
  }

  /** 100 per apple in the basket, minus 25 each time a glove touched an apple of the wrong colour. */
  points() {
    return Math.max(0, (this.score.red + this.score.blue) * 100 - this.wrong * 25)
  }

  /** One star per 2 red + 2 blue apples (2R+2B = 1 star, 4R+4B = 2, 6R+6B = 3). */
  stars() {
    return Math.min(MAX_STARS, Math.floor(this.score.red / 2), Math.floor(this.score.blue / 2))
  }

  applyHands(dt) {
    for (const c of names) {
      const [x, z] = this.pos[c]
      const h = this.hands[c]
      h.root.position.set(x, HAND_Y, z)
      const curl = this.carry[c] ? -1.15 : -0.15
      for (const piv of h.fingers) piv.rotation.x += (curl - piv.rotation.x) * Math.min(1, 14 * dt)
    }
  }

  spawn() {
    const hanging = this.apples.filter((a) => a.state === 'hang')
    if (hanging.length >= 4) return
    let color = choice(names)
    const lc = this.lastColors
    if (lc.length >= 2 && lc[lc.length - 1] === lc[lc.length - 2] && lc[lc.length - 1] === color) color = color === 'red' ? 'blue' : 'red'
    if (!this.free[color].length) return
    let x = 0, z = 0
    for (let i = 0; i < 30; i++) {
      x = uniform(APPLE_AREA[0], APPLE_AREA[1])
      z = uniform(APPLE_AREA[2], APPLE_AREA[3])
      if (hanging.every((a) => Math.hypot(x - a.x, z - a.z) > 1.2)) break
    }
    const ob = this.free[color].pop()
    ob.visible = true
    this.apples.push({ ob, color, state: 'hang', born: this.t, x, y: 0, z, vz: 0, wob: -9, s: 0, tx: 0, ty: 0, rest: 0 })
    lc.push(color)
    sfx.spawn()
  }

  release(a) {
    a.state = 'fall'
    a.vz = 0
    const n = this.inBasket++
    a.tx = BASKET[0] + uniform(-0.6, 0.6)
    a.ty = BASKET[1] + uniform(-0.3, 0.3)
    a.rest = 0.5 + Math.min(n, 7) * 0.08
  }

  update(dt, pad) {
    if (pad.back) return true // O: leave at any time
    const mv = pad.move, lk = pad.look
    const stick = { red: [mv[0] * mv[2], mv[1] * mv[2]], blue: lk }
    for (const c of names) {
      const p = this.pos[c]
      p[0] = clamp(p[0] + stick[c][0] * HAND_SPEED * dt, HAND_BOUNDS[0], HAND_BOUNDS[1])
      p[1] = clamp(p[1] + stick[c][1] * HAND_SPEED * dt, HAND_BOUNDS[2], HAND_BOUNDS[3])
    }
    this.t += dt
    if (this.phase === 'countdown' && this.t >= 0) {
      this.phase = 'play'
      sfx.go()
      this.big = 'GO!'
    }
    if (this.phase === 'play' && this.t >= APPLE_TIME) {
      this.phase = 'done'
      for (const c of names) this.carry[c] = null
      for (const a of this.apples) if (a.state === 'hang' || a.state === 'carried') a.state = 'gone'
    }
    if (this.phase === 'countdown') {
      this.big = String(Math.ceil(-this.t))
      if (this.big !== this.lastCd) {
        this.lastCd = this.big
        sfx.tick()
      }
    }
    else if (this.phase === 'play' && this.t > 0.8) this.big = ''
    else if (this.phase === 'done') {
      // save once the last apple has landed in the basket, so the score is final
      if (!this.rec && !this.apples.some((a) => a.state === 'fall')) {
        this.rec = record('apple', { score: this.points(), stars: this.stars() })
        sfx.result(this.stars(), this.rec.isNewBest)
      }
      this.big = ''
    }

    if (this.phase === 'play') {
      if (this.t >= this.nextSpawn) {
        this.spawn()
        this.nextSpawn = this.t + uniform(0.7, 1.5)
      }
      for (const c of names) {
        if (this.carry[c]) continue
        const px = this.pos[c][0], pz = this.pos[c][1] + 0.5
        for (const a of this.apples) {
          if (a.state !== 'hang' || Math.hypot(a.x - px, a.z - pz) > PICK_R) continue
          if (a.color === c) {
            a.state = 'carried'
            this.carry[c] = a
            sfx.pick()
            break
          }
          if (this.t - a.wob > 0.7) { // wrong glove: the apple just shakes
            a.wob = this.t
            this.wrong++
            this.wrongBy[c]++
            sfx.wrong()
          }
        }
      }
    }

    for (const a of this.apples) {
      const st = a.state
      if (st === 'hang') {
        a.s += (1 - a.s) * Math.min(1, 10 * dt)
        if (this.t - a.born > APPLE_LIFE) a.state = 'gone'
      } else if (st === 'carried') {
        const [hx, hz] = this.pos[a.color]
        a.x = hx
        a.z = hz + 0.58
        a.y = HAND_Y - 0.15
        if (Math.abs(hx - BASKET[0]) < 1.35 && hz < 2.0) { // over the basket: let go
          this.carry[a.color] = null
          this.release(a)
        }
      } else if (st === 'fall') {
        a.vz -= 20 * dt
        a.z += a.vz * dt
        a.x += (a.tx - a.x) * Math.min(1, 8 * dt)
        a.y += (a.ty - a.y) * Math.min(1, 8 * dt)
        if (a.z <= a.rest) {
          a.z = a.rest
          a.state = 'in'
          this.score[a.color]++
          sfx.drop()
        }
      } else if (st === 'gone') {
        a.s -= Math.min(a.s, 8 * dt)
        if (a.s < 0.02) {
          a.s = 0
          a.ob.visible = false
          this.free[a.color].push(a.ob)
          a.state = 'dead'
        }
      }
      if (st === 'carried' || st === 'fall' || st === 'in') a.s += (1 - a.s) * Math.min(1, 12 * dt)
      a.ob.position.set(a.x, a.y, a.z)
      a.ob.scale.setScalar(a.s)
      a.ob.rotation.set(0, 0, 0)
      if (this.t - a.wob < 0.45) a.ob.rotation.y = Math.sin((this.t - a.wob) * 45) * 0.35 // shake on wrong colour
    }
    this.apples = this.apples.filter((a) => a.state !== 'dead')
    this.applyHands(dt)
    return this.phase === 'done' && this.t - APPLE_TIME >= RETURN_DELAY
  }

  ui() {
    const s = this.score
    const left = this.phase === 'countdown' ? APPLE_TIME : Math.max(0, Math.ceil(APPLE_TIME - this.t))
    const chips = [
      { k: 'Time', v: left + 's', tone: this.phase === 'play' && left <= 5 ? 'hot' : '' },
      { k: 'Red', v: s.red, tone: 'red' },
      { k: 'Blue', v: s.blue, tone: 'blue' },
      { k: 'Score', v: this.points(), tone: 'gold' },
    ]
    const hint = 'Left stick: red glove  ·  Right stick: blue glove  ·  O: back'
    if (this.phase === 'done') {
      const result = this.rec && {
        title: "Time's up!",
        rows: [{ k: 'Red apples', v: s.red }, { k: 'Blue apples', v: s.blue }, { k: 'Wrong-colour touches', v: this.wrong }],
        score: this.points(), stars: this.stars(), isNewBest: this.rec.isNewBest, best: this.rec.best,
        secs: Math.max(0, RETURN_DELAY - (this.t - APPLE_TIME)), total: RETURN_DELAY,
      }
      return { hint, chips, banner: result ? null : { title: "Time's up!", lines: [] }, result: result || null }
    }
    return { hint, chips, banner: this.big ? { title: this.big, lines: [] } : null }
  }
}
