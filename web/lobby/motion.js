// DualSense motion sensors over WebHID (Chrome / Edge). The Gamepad API in input.js has no gyro or
// accelerometer, so this opens the same pad as a HID device and keeps the latest raw report.
// Values are the raw int16 units of the DualSense HID report, the units the pattern model was trained on.
// Opening the pad switches a Bluetooth DualSense to full reports, which Chrome's Gamepad API on
// Windows cannot decode (sticks freeze). So while reports arrive, pad() also supplies the sticks and
// buttons in the Gamepad API's standard layout and input.js reads those instead.
const FILTERS = [
  { vendorId: 0x054c, productId: 0x0ce6 }, // DualSense
  { vendorId: 0x054c, productId: 0x0df2 }, // DualSense Edge
]
const STALE_MS = 100

// Chrome scales a 0-255 stick byte to -1..1 this way (128 -> 0.0039), so recordings keep the same values.
const axis = (v) => (v - 127.5) / 127.5
const DPAD_UP = [7, 0, 1], DPAD_RIGHT = [1, 2, 3], DPAD_DOWN = [3, 4, 5], DPAD_LEFT = [5, 6, 7]

function padOf(view, o) {
  const u = (i) => view.getUint8(o + i)
  const b0 = u(7), b1 = u(8), b2 = u(9), hat = b0 & 0x0f
  const bit = (byte, n) => (byte >> n) & 1
  const press = (on) => ({ pressed: on ? 1 : 0, value: on ? 1 : 0 })
  const trigger = (on, v) => ({ pressed: on ? 1 : 0, value: v / 255 })
  // Order matches input.js BUTTON_NAMES (W3C standard mapping).
  const buttons = [
    press(bit(b0, 5)), press(bit(b0, 6)), press(bit(b0, 4)), press(bit(b0, 7)), // cross circle square triangle
    press(bit(b1, 0)), press(bit(b1, 1)), trigger(bit(b1, 2), u(4)), trigger(bit(b1, 3), u(5)), // l1 r1 l2 r2
    press(bit(b1, 4)), press(bit(b1, 5)), press(bit(b1, 6)), press(bit(b1, 7)), // share options l3 r3
    press(DPAD_UP.includes(hat)), press(DPAD_DOWN.includes(hat)), press(DPAD_LEFT.includes(hat)), press(DPAD_RIGHT.includes(hat)),
    press(bit(b2, 0)), press(bit(b2, 1)), // ps touchpad
  ]
  return { connected: true, axes: [axis(u(0)), axis(u(1)), axis(u(2)), axis(u(3)), 0, 0, 0, 0], buttons }
}

function offsetOf(reportId, view) {
  // WebHID drops the report id byte: USB 0x01 starts at the sticks, Bluetooth 0x31 has one sequence byte first.
  if (reportId === 0x01 && view.byteLength >= 53) return 0
  if (reportId === 0x31 && view.byteLength >= 54) return 1
  return null
}

function parse(view, o) {
  const cells = []
  for (let i = 0; i < 3; i++) cells.push(view.getInt16(o + 15 + i * 2, true))
  for (let i = 0; i < 3; i++) cells.push(view.getInt16(o + 21 + i * 2, true))
  for (const p of [32, 36]) {
    const b0 = view.getUint8(o + p), b1 = view.getUint8(o + p + 1), b2 = view.getUint8(o + p + 2), b3 = view.getUint8(o + p + 3)
    cells.push(b0 & 0x80 ? 0 : 1, b1 | ((b2 & 0x0f) << 8), (b2 >> 4) | (b3 << 4))
  }
  cells.push(Math.min((view.getUint8(o + 52) & 0x0f) * 10, 100))
  cells.push((view.getUint8(o + 9) >> 2) & 1)
  return cells
}

class Motion {
  constructor() {
    this.supported = typeof navigator !== 'undefined' && !!navigator.hid
    this.device = null
    this.cells = null
    this.state = null
    this.at = 0
    this.listeners = new Set()
    this.onReport = (e) => {
      const o = offsetOf(e.reportId, e.data)
      if (o === null) return
      this.cells = parse(e.data, o)
      this.state = padOf(e.data, o)
      this.at = performance.now()
    }
    if (!this.supported) return
    navigator.hid.addEventListener('disconnect', (e) => {
      if (e.device !== this.device) return
      this.device = null
      this.cells = null
      this.state = null
      this.changed()
    })
    navigator.hid.addEventListener('connect', (e) => {
      if (!this.device && this.matches(e.device)) this.open(e.device)
    })
    navigator.hid.getDevices().then((devices) => {
      const known = devices.find((d) => this.matches(d))
      if (known && !this.device) this.open(known)
    }).catch(() => {})
  }

  get connected() {
    return !!this.device
  }

  matches(device) {
    return FILTERS.some((f) => f.vendorId === device.vendorId && f.productId === device.productId)
  }

  onChange(f) {
    this.listeners.add(f)
    f(this.connected)
  }

  changed() {
    this.listeners.forEach((f) => f(this.connected))
  }

  /** Must run from a click or key press: the browser shows its device picker. */
  async connect() {
    if (!this.supported || this.device) return
    try {
      const [device] = await navigator.hid.requestDevice({ filters: FILTERS })
      if (device) await this.open(device)
    } catch (error) {
      console.warn('Motion sensors were not connected', error)
    }
  }

  async open(device) {
    try {
      if (!device.opened) await device.open()
      // Bluetooth pads only send gyro and accelerometer after this feature report is read.
      try {
        await device.receiveFeatureReport(0x05)
      } catch {
        /* USB already sends full reports */
      }
      device.addEventListener('inputreport', this.onReport)
      this.device = device
      this.changed()
    } catch (error) {
      console.warn('Motion sensors could not be opened (another app may be using the controller)', error)
    }
  }

  /** The newest 14 motion cells, or null when no report arrived recently. */
  latest() {
    if (!this.cells || performance.now() - this.at > STALE_MS) return null
    return this.cells
  }

  /** Sticks and buttons from the same report, shaped like a Gamepad, or null when no report arrived recently. */
  pad() {
    if (!this.state || performance.now() - this.at > STALE_MS) return null
    return this.state
  }
}

export const motion = new Motion()
