// Game 2 - Harbour Fishing. First person on a dock. The left stick moves the rod tip and traces a random shape
// a fish is swimming along; then the right stick traces a second one; then both fish are reeled into the bucket.
// Like trace.py: velocity-controlled cursor, lane tolerance, % on path. Port of the Blender version.
import * as THREE from 'three'
import { addSun } from './lights.js'
import { record } from './scores.js'
import { sfx } from './audio.js'
import { RETURN_DELAY, TAU, blob, box, catmull, choice, clamp, shuffle, cyl, makeHand, mat, mergeStatic, perspectiveCam, rng, setLens, setSegment, sphere, torus, uniform, unitCyl } from './util.js'

const WY0 = 2 // water-plane origin (world y)
const CAM_POS = new THREE.Vector3(0, -5.5, 5.2)
const LANE_HALF = 0.5, LANE_VIS = 0.42, LANE_STEP = 0.15
const CURSOR_SPEED = 3.2, LEAD = 8
const ROUNDS = 2 // levels: each = one left-hand fish + one right-hand fish
const WATER_X = 4.8, WATER_Y = 2.9 // shapes are designed inside +-WATER_X / +-WATER_Y ...
// ... then moved into the band of water that is clear of the bucket, the gloves and the top bar on a wide screen:
// wy -0.9 .. 4.2, centred on 1.65 (the middle of the view). The cursor is kept inside the same band.
const LANE_CY = 1.65, LANE_SY = 0.88
const CUR_Y0 = LANE_CY - LANE_SY * WATER_Y, CUR_Y1 = LANE_CY + LANE_SY * WATER_Y
const BUCKET = [0, -2.5, 1.85]
const FISH_COL = { A: [0.95, 0.42, 0.08], B: [0.1, 0.55, 0.85] }
const MAX_PTS = 700

/** A random traceable shape across the water: wave / zigzag / loop / S-curve, randomly flipped. */
export const KINDS = ['wave', 'zigzag', 'loop', 'scurve', 'arch', 'spiral', 'figure8', 'hairpin']

function makePath(leftToRight, forcedKind = null) {
  const kind = forcedKind || choice(KINDS)
  const x0 = -4.2, x1 = 4.2
  const flip = choice([-1, 1])
  let ctrl = []
  if (kind === 'wave') {
    const n = 8 + Math.floor(Math.random() * 3), amp = uniform(0.8, 1.6), ph = uniform(0, TAU), cyc = uniform(1.0, 1.8)
    for (let i = 0; i < n; i++) {
      const t = i / (n - 1)
      ctrl.push([x0 + (x1 - x0) * t, amp * Math.sin(TAU * cyc * t + ph)])
    }
  } else if (kind === 'zigzag') {
    const n = 5 + Math.floor(Math.random() * 3), amp = uniform(1.3, 2.0)
    for (let i = 0; i < n; i++) {
      const t = i / (n - 1)
      const y = i === 0 || i === n - 1 ? 0 : amp * (i % 2 ? 1 : -1) * uniform(0.8, 1.0)
      ctrl.push([x0 + (x1 - x0) * t + uniform(-0.15, 0.15), y])
    }
  } else if (kind === 'loop') {
    const r = uniform(0.85, 1.1), cx = uniform(-1.3, 1.3)
    const y0 = uniform(-2.3, 2.3 - 2 * r)
    ctrl.push([x0, y0 + uniform(-0.3, 0.3)], [(x0 + cx) / 2, y0 + uniform(-0.3, 0.3)])
    for (let k = 0; k < 11; k++) {
      const a = ((-90 + k * 30) * Math.PI) / 180 // one full counter-clockwise loop
      ctrl.push([cx + r * Math.cos(a), y0 + r + r * Math.sin(a)])
    }
    ctrl.push([(cx + x1) / 2, y0 + uniform(-0.3, 0.3)], [x1, y0 + uniform(-0.3, 0.3)])
  } else if (kind === 'arch') { // one big half-ellipse hump
    const amp = uniform(1.5, 2.3), y0 = uniform(-2.4, 2.4 - amp)
    for (let k = 0; k <= 14; k++) {
      const a = Math.PI * (1 - k / 14)
      ctrl.push([4.2 * Math.cos(a), y0 + amp * Math.sin(a)])
    }
  } else if (kind === 'spiral') { // inward spiral that ends in the middle
    const cx = uniform(-1.2, 1.2), turns = uniform(1.5, 2.0), r0 = uniform(2.2, 2.5)
    const n = Math.round(turns * 14)
    for (let k = 0; k <= n; k++) {
      const a = (k / n) * turns * TAU
      const rad = r0 - (r0 - 0.55) * (k / n)
      ctrl.push([cx - rad * Math.cos(a), rad * Math.sin(a)])
    }
  } else if (kind === 'figure8') { // lemniscate: crosses itself in the middle
    const ax = uniform(3.2, 3.9), by = uniform(1.6, 2.2)
    for (let k = 0; k <= 24; k++) {
      const t = (k / 24) * TAU
      ctrl.push([-ax * Math.cos(t), by * Math.sin(t) * Math.cos(t) * 1.6])
    }
  } else if (kind === 'hairpin') { // out along the top, a U-turn, and back along the bottom
    const h = uniform(0.8, 1.3), turn = uniform(2.6, 3.1), yo = uniform(-0.4, 0.4)
    ctrl.push([x0, yo + h], [(x0 + turn) / 2, yo + h], [turn, yo + h])
    for (let k = 1; k < 6; k++) {
      const a = Math.PI / 2 - (Math.PI * k) / 6
      ctrl.push([turn + h * Math.cos(a), yo + h * Math.sin(a)])
    }
    ctrl.push([turn, yo - h], [(x0 + turn) / 2, yo - h], [x0, yo - h])
  } else {
    const s = choice([-1, 1])
    for (let i = 0; i < 5; i++) ctrl.push([x0 + ((x1 - x0) * i) / 4, s * (i % 2 ? -1 : 1) * uniform(0.9, 2.0)])
  }
  ctrl = ctrl.map(([x, y]) => [clamp(x, -WATER_X + 0.3, WATER_X - 0.3), clamp(flip * y, -WATER_Y + 0.4, WATER_Y - 0.4)])
  if (!leftToRight) ctrl = ctrl.map(([x, y]) => [-x, y])
  const n = ctrl.length
  const dense = []
  for (let i = 0; i < n - 1; i++) {
    const p0 = ctrl[Math.max(i - 1, 0)], p1 = ctrl[i], p2 = ctrl[i + 1], p3 = ctrl[Math.min(i + 2, n - 1)]
    for (let k = 0; k < 30; k++) dense.push(catmull(p0, p1, p2, p3, k / 30))
  }
  dense.push(ctrl[n - 1])
  const pts = [dense[0]]
  let acc = 0
  for (let i = 1; i < dense.length; i++) {
    acc += Math.hypot(dense[i][0] - dense[i - 1][0], dense[i][1] - dense[i - 1][1])
    if (acc >= LANE_STEP) {
      pts.push(dense[i])
      acc = 0
    }
  }
  return { pts: pts.slice(0, MAX_PTS - 1).map(([x, y]) => [x, LANE_CY + LANE_SY * y]), kind }
}

function buildFish(rgb) {
  const g = new THREE.Group()
  const body = mat(rgb, { rough: 0.4 }), fin = mat(rgb.map((c) => c * 0.65), { rough: 0.5 }), eye = mat([0.02, 0.02, 0.02], { rough: 0.3 })
  sphere(g, 0.5, [0, 0, 0], body, [1, 0.42, 0.5], 10)
  const tail = cyl(g, 0.34, 0.6, [-0.68, 0, 0], fin, 3, 0)
  tail.scale.set(1, 0.2, 1)
  tail.rotation.y = Math.PI / 2
  cyl(g, 0.14, 0.3, [0, 0, 0.26], fin, 3, 0)
  for (const sy of [-0.17, 0.17]) sphere(g, 0.07, [0.34, sy, 0.08], eye, [1, 1, 1], 6)
  g.visible = false
  return g
}

function ribbonGeometry() {
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(MAX_PTS * 2 * 3), 3))
  const idx = new Uint32Array((MAX_PTS - 1) * 6)
  for (let i = 0; i < MAX_PTS - 1; i++) idx.set([2 * i, 2 * i + 1, 2 * i + 3, 2 * i, 2 * i + 3, 2 * i + 2], i * 6)
  g.setIndex(new THREE.BufferAttribute(idx, 1))
  g.setDrawRange(0, 0)
  return g
}

export class FishGame {
  constructor() {
    this.scene = new THREE.Scene()
    this.scene.background = new THREE.Color().setRGB(0.45, 0.68, 0.95, THREE.LinearSRGBColorSpace)
    addSun(this.scene, { intensity: 6, fill: 1.8, extent: 24 })
    const st = new THREE.Group()
    this.scene.add(st)
    const water = mat([0.08, 0.42, 0.62], { rough: 0.12 })
    const deck = mat([0.5, 0.34, 0.18], { rough: 0.9 }), deck2 = mat([0.3, 0.19, 0.09], { rough: 0.9 })
    const hill = [mat([0.2, 0.45, 0.22]), mat([0.27, 0.52, 0.25])]
    const white = mat([0.93, 0.93, 0.95], { rough: 0.6 }), red = mat([0.8, 0.12, 0.1], { rough: 0.6 })
    const hull = mat([0.2, 0.25, 0.55], { rough: 0.6 }), cabin = mat([0.9, 0.85, 0.7], { rough: 0.7 })
    const lamp = mat([1, 0.9, 0.5], { rough: 0.3, emit: [1, 0.85, 0.4], emitK: 3 })
    const wood = mat([0.28, 0.18, 0.09], { rough: 0.95 })
    box(st, [70, 70, 0.4], [0, WY0 + 10, -0.2], water)
    box(st, [22, 10, 0.3], [0, -7.2, 1.35], deck) // deck top z=1.5, edge at y=-2.2
    for (let i = -10; i <= 10; i += 2) box(st, [0.05, 10, 0.02], [i, -7.2, 1.51], deck2)
    for (const sx of [-5.8, 5.8]) {
      cyl(st, 0.2, 3.0, [sx, -2.5, 1.0], wood, 6)
      sphere(st, 0.22, [sx, -2.5, 2.5], wood, [1, 1, 0.6], 6)
    }
    const r = rng(3)
    for (let k = 0; k < 7; k++) blob(st, 7 + r() * 3, [-36 + k * 12, 28 + (r() * 5 - 2), 0], hill[k % 2], 0.4, 90 + k)
    cyl(st, 1.2, 8.0, [-13, 17, 4.0], white, 10, 0.8)
    cyl(st, 1.0, 1.3, [-13, 17, 3.0], red, 10, 0.95)
    cyl(st, 0.92, 1.3, [-13, 17, 5.6], red, 10, 0.85)
    cyl(st, 0.9, 1.0, [-13, 17, 8.5], lamp, 8)
    cyl(st, 1.1, 0.9, [-13, 17, 9.4], red, 8, 0)
    for (const [bx, by, ry, col] of [[6.5, 11, 0.3, hull], [-7.5, 8, -0.5, red]]) {
      box(st, [3.2, 1.2, 0.7], [bx, by, 0.15], col, [0, 0, ry])
      box(st, [1.1, 0.8, 0.7], [bx + Math.cos(ry) * 0.3, by + Math.sin(ry) * 0.3, 0.85], cabin, [0, 0, ry])
      cyl(st, 0.05, 2.6, [bx - Math.cos(ry) * 0.6, by - Math.sin(ry) * 0.6, 1.6], wood, 5)
    }
    for (const [bx, by] of [[-5.4, WY0 - 0.5], [5.5, WY0 + 1.0], [-5.6, WY0 + 3.8], [5.4, WY0 + 4.2]]) {
      sphere(st, 0.28, [bx, by, 0.1], red, [1, 1, 1], 6)
      cyl(st, 0.12, 0.35, [bx, by, 0.45], white, 6, 0.04)
    }
    // open bucket the fish land in
    const bw = mat([0.45, 0.3, 0.16], { rough: 0.9, side: THREE.DoubleSide })
    const bg = new THREE.CylinderGeometry(0.72, 0.55, 0.75, 16, 1, true)
    bg.rotateX(Math.PI / 2)
    const bk = new THREE.Mesh(bg, bw)
    bk.position.set(...BUCKET)
    bk.castShadow = bk.receiveShadow = true
    this.scene.add(bk)
    cyl(this.scene, 0.5, 0.05, [BUCKET[0], BUCKET[1], BUCKET[2] - 0.3], mat([0.1, 0.07, 0.04]), 16)
    mergeStatic(st)

    this.camera = perspectiveCam(28, 100)
    this.camera.position.copy(CAM_POS)
    const pitch = (30 * Math.PI) / 180 // looking 30 degrees below the horizon
    this.camera.lookAt(0, CAM_POS.y + 10 * Math.cos(pitch), CAM_POS.z - 10 * Math.sin(pitch))
    this.camera.updateMatrixWorld(true)

    // gloves rest at the bottom corners of the view
    const fwd = new THREE.Vector3(0, 0, -1).applyQuaternion(this.camera.quaternion)
    const up = new THREE.Vector3(0, 1, 0).applyQuaternion(this.camera.quaternion)
    this.dirf = fwd.multiplyScalar(Math.cos(0.35)).add(up.multiplyScalar(Math.sin(0.35))).normalize()
    this.hands = {}
    this.grip = {}
    this.fingers = {}
    for (const [side, rgb, lx] of [['left', [0.8, 0.02, 0.02], -1.45], ['right', [0.03, 0.12, 0.9], 1.45]]) {
      const h = makeHand(rgb, { flip: true })
      const pos = this.camera.localToWorld(new THREE.Vector3(lx, -1.1, -3.2))
      h.root.position.copy(pos)
      const z = this.dirf.clone()
      const x = new THREE.Vector3(0, 0, 1).cross(z).normalize()
      const y = z.clone().cross(x)
      h.root.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(x, y, z))
      h.root.scale.setScalar(0.8)
      this.scene.add(h.root)
      this.hands[side] = h.root
      this.fingers[side] = h.fingers
      this.grip[side] = pos.clone().addScaledVector(this.dirf, 0.35)
    }
    this.fish = { left: buildFish(FISH_COL.A), right: buildFish(FISH_COL.B) }
    this.scene.add(this.fish.left, this.fish.right)

    this.rod = unitCyl(0.06, 0.02, mat([0.3, 0.2, 0.1], { rough: 0.5 }), 6)
    this.line = unitCyl(0.012, 0.012, mat([0.95, 0.95, 0.95], { rough: 0.4, emit: [1, 1, 1], emitK: 1.5 }), 4)
    this.matOn = mat([0.15, 0.95, 0.35], { rough: 0.3, emit: [0.15, 0.95, 0.35], emitK: 3 })
    this.matOff = mat([0.95, 0.15, 0.15], { rough: 0.3, emit: [0.95, 0.15, 0.15], emitK: 3 })
    this.lure = sphere(null, 0.14, [0, 0, 0], this.matOn, [1, 1, 1], 8)
    const glow = mat([0.9, 0.97, 1], { rough: 0.3, emit: [0.9, 0.97, 1], emitK: 2 })
    const gold = mat([1, 0.8, 0.2], { rough: 0.3, emit: [1, 0.75, 0.1], emitK: 2 })
    this.ripple = torus(null, 0.32, 0.04, [0, 0, 0], glow, 16, 4)
    this.mstart = torus(null, 0.6, 0.04, [0, 0, 0], gold, 16, 4)
    this.mend = torus(null, 0.6, 0.04, [0, 0, 0], gold, 16, 4)
    const flat = (rgb) => new THREE.MeshBasicMaterial({ color: new THREE.Color().setRGB(...rgb, THREE.LinearSRGBColorSpace), polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 })
    this.lane = new THREE.Mesh(ribbonGeometry(), flat([0.55, 0.9, 1.0]))
    this.done = new THREE.Mesh(ribbonGeometry(), flat([0.2, 1.0, 0.4]))
    this.lane.frustumCulled = this.done.frustumCulled = false
    this.scene.add(this.rod, this.line, this.lure, this.ripple, this.mstart, this.mend, this.lane, this.done)
    this.start()
  }

  resize(aspect) {
    setLens(this.camera, 28, aspect)
  }

  w(p, z = 0.04) {
    return new THREE.Vector3(p[0], WY0 + p[1], z)
  }

  ribbon(mesh, pts, upto, z) {
    const n = upto === null ? pts.length : upto + 1
    const pos = mesh.geometry.attributes.position.array
    for (let i = 0; i < n; i++) {
      const [x, y] = pts[i]
      const a = pts[Math.max(i - 1, 0)], b = pts[Math.min(i + 1, pts.length - 1)]
      const dx = b[0] - a[0], dy = b[1] - a[1]
      const l = Math.hypot(dx, dy) || 1
      const nx = (-dy / l) * LANE_VIS, ny = (dx / l) * LANE_VIS
      pos.set([x + nx, WY0 + y + ny, z, x - nx, WY0 + y - ny, z], i * 6)
    }
    mesh.geometry.attributes.position.needsUpdate = true
    mesh.geometry.setDrawRange(0, Math.max(n - 1, 0) * 6)
  }

  start() {
    this.round = 0
    this.caught = 0
    this.stats = []
    this.kindQueue = shuffle([...KINDS]) // every trace in a game gets a different shape type
    this.traceN = 0
    this.clock = 0
    this.timer = 2.8
    this.state = 'intro'
    this.side = 'left'
    this.fishPos = { left: new THREE.Vector3(), right: new THREE.Vector3() }
    this.fishHead = { left: 0, right: 0 }
    this.cur = [0, 0]
    this.pts = [[0, 0], [1, 0]]
    this.prog = 0
    this.kind = ''
    for (const f of Object.values(this.fish)) f.visible = false
    this.lane.geometry.setDrawRange(0, 0)
    this.done.geometry.setDrawRange(0, 0)
    this.bigText = 'Harbour Fishing\nTrace the fish!\nLeft stick first, then right'
    this.placeCursor()
  }

  beginTrace(side) {
    this.side = side
    const { pts, kind } = makePath(side === 'left', this.kindQueue[this.traceN++ % this.kindQueue.length])
    this.pts = pts
    this.kind = kind
    this.prog = 0
    this.cur = [...pts[0]]
    this.frames = this.onFrames = this.offCount = 0
    this.off = false
    this.tTrace = 0
    this.state = 'trace'
    sfx.cast()
    this.banner = 1.6
    this.ribbon(this.lane, pts, null, 0.04)
    this.ribbon(this.done, pts, 0, 0.06)
    this.mstart.position.copy(this.w(pts[0], 0.07))
    this.mend.position.copy(this.w(pts[pts.length - 1], 0.07))
    const f = this.fish[side]
    f.visible = true
    this.fishPos[side] = this.w(pts[0], 0.12)
    this.fishHead[side] = Math.atan2(pts[1][1] - pts[0][1], pts[1][0] - pts[0][0])
    this.bigText = `Round ${this.round + 1}/${ROUNDS}   ${side === 'left' ? 'LEFT' : 'RIGHT'} hand: trace the fish!`
  }

  placeCursor() {
    const c = this.w(this.cur, 0.1)
    this.lure.position.copy(c)
    this.ripple.position.copy(c)
    const grip = this.grip[this.side]
    const tip = grip.clone().lerp(c, 0.55)
    tip.z = 3.7
    setSegment(this.rod, grip, tip)
    setSegment(this.line, tip, c)
  }

  update(dt, pad) {
    if (pad.back) return true // O: leave at any time
    this.clock += dt
    const mv = pad.move
    const stick = this.side === 'left' ? [mv[0] * mv[2], mv[1] * mv[2]] : pad.look
    if (this.state === 'intro') {
      this.timer -= dt
      if (this.timer <= 0) this.beginTrace('left')
    } else if (this.state === 'trace') {
      this.tTrace += dt
      this.banner -= dt
      if (this.banner < 0) this.bigText = ''
      const cur = this.cur
      cur[0] = clamp(cur[0] + stick[0] * CURSOR_SPEED * dt, -WATER_X, WATER_X)
      cur[1] = clamp(cur[1] + stick[1] * CURSOR_SPEED * dt, CUR_Y0, CUR_Y1)
      const n = this.pts.length
      let best = this.prog
      for (let k = this.prog + 1; k < Math.min(this.prog + 14, n); k++) { // advance along the shape in order
        if (Math.hypot(this.pts[k][0] - cur[0], this.pts[k][1] - cur[1]) < LANE_HALF) best = k
      }
      if (best > this.prog) {
        this.prog = best
        sfx.progress(this.prog / this.pts.length)
        this.ribbon(this.done, this.pts, this.prog, 0.06)
      }
      let near = Infinity
      for (let k = Math.max(0, this.prog - 5); k < Math.min(n, this.prog + 14); k++) near = Math.min(near, Math.hypot(this.pts[k][0] - cur[0], this.pts[k][1] - cur[1]))
      const off = near > LANE_HALF
      if (off && !this.off) {
        this.offCount++
        sfx.offLane()
      }
      this.off = off
      this.frames++
      if (!off) this.onFrames++
      this.lure.material = off ? this.matOff : this.matOn
      if (this.prog >= n - 3) {
        const pct = (100 * this.onFrames) / Math.max(this.frames, 1)
        this.stats.push({ round: this.round + 1, side: this.side, shape: this.kind, time: +this.tTrace.toFixed(2), pct: Math.round(pct), off: this.offCount, score: Math.round(pct * 6 + Math.max(0, 12 - this.tTrace) * 25) })
        if (this.side === 'left') {
          this.state = 'switch'
          this.timer = 1.4
          this.bigText = 'Hooked one!\nNow the RIGHT hand'
          sfx.hooked()
        } else {
          this.state = 'capture'
          this.timer = 1.8
          this.capFrom = { left: this.fishPos.left.clone(), right: this.fishPos.right.clone() }
          this.bigText = 'Caught!'
          sfx.splash()
        }
      }
    } else if (this.state === 'switch') {
      this.timer -= dt
      if (this.timer <= 0) this.beginTrace('right')
    } else if (this.state === 'capture') {
      this.timer -= dt
      const q = 1 - Math.max(this.timer, 0) / 1.8
      ;['left', 'right'].forEach((s, i) => {
        const qs = clamp((q - 0.25 * i) / 0.75, 0, 1)
        const end = new THREE.Vector3(BUCKET[0] + (i === 0 ? -0.15 : 0.15), BUCKET[1], BUCKET[2] + 0.35)
        const pos = this.capFrom[s].clone().lerp(end, qs)
        pos.z += 3.0 * Math.sin(Math.PI * qs)
        this.fishPos[s] = pos
        this.fishHead[s] += 12 * dt
        if (qs >= 1 && this.fish[s].visible) {
          this.fish[s].visible = false
          this.caught++
          sfx.drop()
        }
      })
      if (this.timer <= 0) {
        this.round++
        if (this.round >= ROUNDS) this.finishGame()
        else this.beginTrace('left')
      }
    } else if (this.state === 'done') {
      this.timer += dt
      return this.timer >= RETURN_DELAY
    }
    this.animateFish(dt)
    this.placeCursor()
    for (const side of ['left', 'right']) { // the active glove grips the rod
      const curl = side === this.side && ['trace', 'switch', 'capture'].includes(this.state) ? -0.9 : -0.1
      for (const piv of this.fingers[side]) piv.rotation.x += (curl - piv.rotation.x) * Math.min(1, 12 * dt)
    }
    const pulse = 1 + 0.25 * Math.sin(this.clock * 6)
    this.ripple.scale.set(pulse, pulse, 1)
    this.mend.scale.set(pulse, pulse, 1)
    return false
  }

  animateFish(dt) {
    const k = Math.min(1, 10 * dt)
    for (const side of ['left', 'right']) {
      const f = this.fish[side]
      if (!f.visible) continue
      if (this.state === 'trace' && side === this.side) { // the fish swims ahead of the rod tip
        const i = Math.min(this.prog + LEAD, this.pts.length - 1)
        const tgt = this.w(this.pts[i], 0.12)
        const a = this.pts[Math.max(i - 1, 0)], b = this.pts[Math.min(i + 1, this.pts.length - 1)]
        const head = Math.atan2(b[1] - a[1], b[0] - a[0])
        this.fishPos[side].lerp(tgt, k)
        const d = ((head - this.fishHead[side] + Math.PI) % TAU + TAU) % TAU - Math.PI
        this.fishHead[side] += d * k
      }
      const sway = 0.25 * Math.sin(this.clock * 12 + (side === 'left' ? 0 : 2))
      const hooked = (this.state === 'trace' && side === 'left' && this.side === 'right') || this.state === 'switch'
      f.position.copy(this.fishPos[side])
      if (hooked) f.position.z += 0.12 * Math.sin(this.clock * 9)
      if (this.state === 'capture') f.rotation.set(this.fishHead[side], 0, 0.6)
      else f.rotation.set(0, hooked ? 0.15 * Math.sin(this.clock * 10) : 0, this.fishHead[side] + sway)
      f.scale.setScalar(1.5)
    }
  }

  finishGame() {
    this.state = 'done'
    this.timer = 0
    this.rec = record('fish', { score: this.points(), stars: this.stars() })
    sfx.result(this.stars(), this.rec.isNewBest)
    this.bigText = ''
    this.lure.material = this.matOn
  }

  /** Each trace scores up to 900: 6 per % of the time you stayed on the lane (max 600) + 25 per second under 12 s (max 300). */
  points() {
    return this.stats.reduce((sum, s) => sum + s.score, 0)
  }

  avgPct() {
    return this.stats.length ? Math.round(this.stats.reduce((sum, s) => sum + s.pct, 0) / this.stats.length) : 0
  }

  /** Stars from how accurately you traced on average: 60% = 1 star, 80% = 2, 92% = 3. */
  stars() {
    const a = this.avgPct()
    return a >= 92 ? 3 : a >= 80 ? 2 : a >= 60 ? 1 : 0
  }

  ui() {
    const chips = [
      { k: 'Round', v: `${Math.min(this.round + 1, ROUNDS)}/${ROUNDS}` },
      { k: 'Caught', v: this.caught },
      { k: 'Score', v: this.points(), tone: 'gold' },
    ]
    if (this.state === 'trace') chips.unshift({ k: 'Hand', v: this.side === 'left' ? 'LEFT' : 'RIGHT', tone: this.side === 'left' ? 'red' : 'blue' })
    const hint = 'Left stick traces the first fish  ·  Right stick the second  ·  stay on the glowing lane  ·  O: back'
    if (this.state === 'done') {
      return {
        hint, chips, banner: null,
        result: {
          title: 'Fishing complete!',
          rows: [{ k: 'Fish caught', v: this.caught }, { k: 'On the lane', v: this.avgPct() + '%' }],
          score: this.points(), stars: this.stars(), isNewBest: this.rec.isNewBest, best: this.rec.best,
          secs: Math.max(0, RETURN_DELAY - this.timer), total: RETURN_DELAY,
        },
      }
    }
    const lines = this.bigText ? this.bigText.split('\n') : []
    return { hint, chips, banner: lines.length ? { title: lines[0], lines: lines.slice(1) } : null }
  }
}
