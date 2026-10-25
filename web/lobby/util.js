// Shared helpers for the 3D lobby. Everything uses Blender-style axes: +Z is up, +X right, +Y forward.
import * as THREE from 'three'
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js'

THREE.Object3D.DEFAULT_UP.set(0, 0, 1) // must run before any camera/object is created

export const TAU = Math.PI * 2
export const RETURN_DELAY = 3 // seconds the results show before going back to the lobby
export const clamp = (v, a, b) => Math.min(Math.max(v, a), b)
export const uniform = (a, b) => a + Math.random() * (b - a)
export const choice = (arr) => arr[Math.floor(Math.random() * arr.length)]
export function shuffle(arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[arr[i], arr[j]] = [arr[j], arr[i]]
  }
  return arr
}

/** Seeded RNG (mulberry32) for repeatable scenery. */
export function rng(seed) {
  let s = seed >>> 0
  return () => {
    s = (s + 0x6d2b79f5) >>> 0
    let t = s
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

// ---- materials (rgb are the same linear values the Blender build used) -----------------
const cache = new Map()
export function mat(rgb, { rough = 0.85, emit = null, emitK = 0, flat = true, side = THREE.FrontSide } = {}) {
  const key = JSON.stringify([rgb, rough, emit, emitK, flat, side])
  let m = cache.get(key)
  if (!m) {
    m = new THREE.MeshStandardMaterial({
      color: new THREE.Color().setRGB(rgb[0], rgb[1], rgb[2], THREE.LinearSRGBColorSpace),
      roughness: rough,
      metalness: 0,
      flatShading: flat,
      side,
    })
    if (emit) {
      m.emissive = new THREE.Color().setRGB(emit[0], emit[1], emit[2], THREE.LinearSRGBColorSpace)
      m.emissiveIntensity = emitK
    }
    cache.set(key, m)
  }
  return m
}
/** An uncached material, for things whose colour changes at runtime. */
export function ownMat(rgb, opts = {}) {
  const m = mat(rgb, opts).clone()
  return m
}

// ---- low-poly primitives (z-up) ---------------------------------------------------------
function finish(mesh, parent, pos, shadow = true) {
  mesh.position.set(pos[0], pos[1], pos[2])
  mesh.castShadow = shadow
  mesh.receiveShadow = true
  if (parent) parent.add(mesh)
  return mesh
}

/** Cylinder / cone along +Z: r is the bottom radius, r2 the top radius (defaults to r). */
export function cyl(parent, r, h, pos, material, segs = 12, r2 = null, shadow = true) {
  const g = new THREE.CylinderGeometry(r2 === null ? r : r2, r, h, Math.min(segs, 20))
  g.rotateX(Math.PI / 2)
  return finish(new THREE.Mesh(g, material), parent, pos, shadow)
}

export function box(parent, size, pos, material, rot = [0, 0, 0], shadow = true) {
  const m = finish(new THREE.Mesh(new THREE.BoxGeometry(size[0], size[1], size[2]), material), parent, pos, shadow)
  m.rotation.set(rot[0], rot[1], rot[2])
  return m
}

export function sphere(parent, r, pos, material, scale = [1, 1, 1], seg = 10, shadow = true) {
  const g = new THREE.SphereGeometry(r, seg, Math.max(3, Math.floor(seg / 2)))
  g.rotateX(Math.PI / 2)
  const m = finish(new THREE.Mesh(g, material), parent, pos, shadow)
  m.scale.set(scale[0], scale[1], scale[2])
  return m
}

export function torus(parent, major, minor, pos, material, segs = 20, tube = 4) {
  return finish(new THREE.Mesh(new THREE.TorusGeometry(major, minor, tube, segs), material), parent, pos)
}

/** Jittered icosphere: the lumpy canopy / rock look. The jitter depends only on position, so shared
 *  corners move together and the mesh stays watertight. */
export function blob(parent, r, pos, material, squash = 1, seed = 0, detail = 1) {
  const g = new THREE.IcosahedronGeometry(r, detail)
  const p = g.attributes.position
  for (let i = 0; i < p.count; i++) {
    const x = p.getX(i), y = p.getY(i), z = p.getZ(i)
    const n = Math.sin((x + seed) * 12.9898 + (y - seed) * 78.233 + z * 37.719) * 43758.5453
    const k = 0.88 + 0.24 * (n - Math.floor(n))
    p.setXYZ(i, x * k, y * k, z * k * squash)
  }
  g.computeVertexNormals()
  return finish(new THREE.Mesh(g, material), parent, pos)
}

/** Merge every plain mesh under `group` into one mesh per material (group must sit at the origin).
 *  Hundreds of draw calls become a few dozen. */
export function mergeStatic(group) {
  group.updateMatrixWorld(true)
  const buckets = new Map()
  const meshes = []
  group.traverse((o) => {
    if (o.isMesh && !o.userData.keep) meshes.push(o)
  })
  for (const o of meshes) {
    let g = o.geometry.clone()
    g.applyMatrix4(o.matrixWorld)
    if (g.index) g = g.toNonIndexed()
    for (const name of Object.keys(g.attributes)) if (name !== 'position' && name !== 'normal') g.deleteAttribute(name)
    if (!buckets.has(o.material)) buckets.set(o.material, [])
    buckets.get(o.material).push(g)
    o.removeFromParent()
    o.geometry.dispose()
  }
  for (const [material, geoms] of buckets) {
    const merged = new THREE.Mesh(mergeGeometries(geoms, false), material)
    merged.castShadow = merged.receiveShadow = true
    group.add(merged)
    geoms.forEach((g) => g.dispose())
  }
  // drop the now-empty subgroups
  for (const c of [...group.children]) if (!c.isMesh && !c.children.length) c.removeFromParent()
}

/** Text lying on the ground (readable from above) or standing up, drawn to a canvas. */
export function textSprite(text, { size = 0.5, color = '#ffffff', width = 6, bold = true } = {}) {
  const lines = text.split('\n')
  const c = document.createElement('canvas')
  c.width = 1024
  c.height = 128 * lines.length
  const ctx = c.getContext('2d')
  ctx.font = `${bold ? '700 ' : ''}96px "Fredoka", "Atkinson Hyperlegible", system-ui, sans-serif`
  ctx.fillStyle = color
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  lines.forEach((l, i) => ctx.fillText(l, 512, 64 + i * 128))
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  const m = new THREE.Mesh(
    new THREE.PlaneGeometry(width, (width * c.height) / c.width),
    new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false, toneMapped: false }),
  )
  m.scale.setScalar(size / 0.5)
  return m
}

/** Match a Blender perspective camera: `lens` mm on a 36 mm sensor fitted to the larger dimension. */
export function setLens(cam, lens, aspect) {
  const half = Math.atan(18 / lens)
  const vfov = aspect >= 1 ? 2 * Math.atan(Math.tan(half) / aspect) : 2 * half
  cam.fov = (vfov * 180) / Math.PI
  cam.aspect = aspect
  cam.updateProjectionMatrix()
}

export function perspectiveCam(lens, far = 100) {
  const cam = new THREE.PerspectiveCamera(50, 1.6, 0.1, far)
  cam.userData.lens = lens
  setLens(cam, lens, 1.6)
  return cam
}

/** Stretch a unit-length (along +Z, origin at base) mesh between two points. */
const Z = new THREE.Vector3(0, 0, 1)
const tmp = new THREE.Vector3()
export function setSegment(mesh, a, b) {
  tmp.subVectors(b, a)
  const len = tmp.length()
  mesh.position.copy(a)
  if (len > 1e-6) mesh.quaternion.setFromUnitVectors(Z, tmp.multiplyScalar(1 / len))
  mesh.scale.set(1, 1, len)
}
export function unitCyl(r1, r2, material, segs = 6) {
  const g = new THREE.CylinderGeometry(r2, r1, 1, segs)
  g.rotateX(Math.PI / 2)
  g.translate(0, 0, 0.5)
  const m = new THREE.Mesh(g, material)
  m.castShadow = true
  return m
}

/** Uniform Catmull-Rom point between p1 and p2. */
export function catmull(p0, p1, p2, p3, t) {
  return p1.map(
    (b, i) =>
      0.5 *
      (2 * b + (-p0[i] + p2[i]) * t + (2 * p0[i] - 5 * b + 4 * p2[i] - p3[i]) * t * t + (-p0[i] + 3 * b - 3 * p2[i] + p3[i]) * t ** 3),
  )
}

/** The gloved hand used by the apple / fishing / rat games. Model points along +Z (fingers), palm thickness
 *  along Y, thumb on +X (red) or -X (flipped). */
export function makeHand(rgb, { flip = false, arm = true, glove = null } = {}) {
  const root = new THREE.Group()
  const g = glove || mat(rgb, { rough: 0.55, emit: rgb, emitK: 0.5 })
  const cuffM = mat([0.95, 0.95, 0.95], { rough: 0.7 })
  const sleeveM = mat([0.55, 0.3, 0.45])
  box(root, [0.62, 0.3, 0.62], [0, 0, 0], g)
  if (arm) {
    cyl(root, 0.33, 0.2, [0, 0, -0.42], cuffM, 16)
    cyl(root, 0.27, 3.2, [0, 0, -2.0], sleeveM, 12)
  }
  const fingers = []
  ;[[-0.21, 0.5], [-0.07, 0.6], [0.07, 0.56], [0.21, 0.46]].forEach(([fx, h]) => {
    const piv = new THREE.Group()
    piv.position.set(fx, 0, 0.28)
    cyl(piv, 0.085, h, [0, 0, h / 2], g, 10)
    root.add(piv)
    fingers.push(piv)
  })
  const side = (flip ? -1 : 1) // red hand: thumb toward +X
  const thumb = new THREE.Group()
  thumb.position.set(side * 0.3, 0, -0.05)
  cyl(thumb, 0.09, 0.42, [0, 0, 0.21], g, 10)
  thumb.rotation.y = side * 0.9
  root.add(thumb)
  return { root, fingers, thumb }
}
