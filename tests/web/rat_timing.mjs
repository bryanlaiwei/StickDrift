// Nose and tail crossings use the rat mesh and the hand's landing box.
globalThis.window = { addEventListener() {} }
globalThis.document = { addEventListener() {}, hidden: false }
globalThis.localStorage = { getItem() { return null }, setItem() {} }

const { NOSE_AT, TAIL_AT, crossTime } = await import('../../web/lobby/rat.js')

if (Math.abs(NOSE_AT - 2.446) > 1e-9) throw new Error(`nose edge ${NOSE_AT}`)
if (Math.abs(TAIL_AT - (-1.6)) > 1e-9) throw new Error(`tail edge ${TAIL_AT}`)

const nose = crossTime(3, 2, NOSE_AT, 0, 1)
if (Math.abs(nose - (3 - NOSE_AT)) > 1e-9) throw new Error(`nose time ${nose}`)
if (crossTime(3, 2.5, NOSE_AT, 0, 1) !== null) throw new Error('nose should still be short of the hand')
if (crossTime(-1, -2, TAIL_AT, 1, 2) === null) throw new Error('tail should cross the far edge')

console.log('rat timing ok')
