import { useEffect, useRef, useState } from 'react'
import { api, type LiveSample, type LiveSnapshot, type LiveStatus } from '../../api'

const KEEP = 100 * 40 // samples kept for the charts (~40 s)
const DELAY_MS = 150 // jitter buffer: samples play back this far behind their arrival, evenly spaced
const MAX_GAP_S = 0.1 // longest pause played back between two samples (level changes reset the game clock)
const DONE: LiveStatus[] = ['finished', 'failed', 'lost', 'ended']

export type FeedMode = 'connecting' | 'live' | 'polling'

type Msg =
  | ({ type: 'snapshot' } & LiveSnapshot)
  | ({ type: 'state' } & Omit<LiveSnapshot, 'samples'>)
  | { type: 'samples'; samples: LiveSample[] }
  | { type: 'resync' }

function socketUrl(id: string) {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}/api/caregiver/live/${id}/ws`
}

/**
 * A live session pushed over a WebSocket (polling if that is not possible), with the samples played back
 * smoothly: each batch arrives every ~100 ms, so samples are released one by one at the pace they were
 * recorded instead of jumping in clumps.
 */
export function useLiveFeed(id: string) {
  const [snap, setSnap] = useState<LiveSnapshot | null>(null)
  const [samples, setSamples] = useState<LiveSample[]>([])
  const [error, setError] = useState<string | null>(null)
  const [mode, setMode] = useState<FeedMode>('connecting')

  const shown = useRef<LiveSample[]>([])
  const queue = useRef<{ s: LiveSample; at: number }[]>([])
  const lastSeq = useRef(0)
  const lastAt = useRef(0)

  useEffect(() => {
    let stop = false
    let ws: WebSocket | null = null
    let timer = 0
    let raf = 0
    let failures = 0
    shown.current = []
    queue.current = []
    lastSeq.current = 0
    lastAt.current = 0
    setSamples([])
    setSnap(null)

    /** Show these at once (the history in a snapshot). */
    const showNow = (rows: LiveSample[]) => {
      const fresh = rows.filter((r) => r[0] > lastSeq.current)
      if (!fresh.length) return
      lastSeq.current = fresh[fresh.length - 1][0]
      shown.current = [...shown.current, ...fresh].slice(-KEEP)
      setSamples(shown.current)
    }

    /** Spread a new batch over the time it covers, ending DELAY_MS from now. */
    const enqueue = (rows: LiveSample[]) => {
      const fresh = rows.filter((r) => r[0] > lastSeq.current)
      if (!fresh.length) return
      lastSeq.current = fresh[fresh.length - 1][0]
      const now = performance.now() + DELAY_MS
      const at = new Array<number>(fresh.length)
      at[fresh.length - 1] = now
      for (let k = fresh.length - 2; k >= 0; k--) {
        const gap = Math.min(Math.max(fresh[k + 1][2] - fresh[k][2], 0), MAX_GAP_S)
        at[k] = at[k + 1] - gap * 1000
      }
      fresh.forEach((s, k) => {
        lastAt.current = Math.max(lastAt.current, at[k]) // never play out of order
        queue.current.push({ s, at: lastAt.current })
      })
    }

    const play = () => {
      raf = requestAnimationFrame(play)
      const q = queue.current
      if (!q.length || q[0].at > performance.now()) return
      const now = performance.now()
      let n = 0
      while (n < q.length && q[n].at <= now) n++
      shown.current = [...shown.current, ...q.splice(0, n).map((x) => x.s)].slice(-KEEP)
      setSamples(shown.current)
    }
    raf = requestAnimationFrame(play)

    const poll = async () => {
      try {
        const s = await api.caregiverLiveSnapshot(id, lastSeq.current)
        if (stop) return
        setError(null)
        setSnap(s)
        if (lastSeq.current === 0) showNow(s.samples)
        else enqueue(s.samples)
        const done = DONE.includes(s.status)
        if (!done || !s.result || s.hand_replay_pending) timer = window.setTimeout(poll, done ? 3000 : 250)
      } catch (e) {
        if (stop) return
        setError((e as Error).message)
        timer = window.setTimeout(poll, 2000)
      }
    }

    const connect = () => {
      if (stop) return
      setMode('connecting')
      let opened = false
      ws = new WebSocket(socketUrl(id))
      ws.onopen = () => {
        opened = true
        failures = 0
        setMode('live')
        setError(null)
      }
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data as string) as Msg
        if (msg.type === 'snapshot') {
          setSnap(msg)
          if (lastSeq.current === 0) showNow(msg.samples)
          else enqueue(msg.samples) // a reconnect: only what was missed
        } else if (msg.type === 'samples') {
          enqueue(msg.samples)
        } else if (msg.type === 'state') {
          setSnap((prev) => ({ ...msg, samples: prev?.samples ?? [] }))
        } else if (msg.type === 'resync') {
          ws?.close()
        }
      }
      ws.onclose = (ev) => {
        if (stop) return
        if (ev.code === 4401 || ev.code === 4403) {
          setError('Please log in again to watch live.')
          return
        }
        if (ev.code === 4404) {
          setError('That live session was not found.')
          return
        }
        failures = opened ? 0 : failures + 1
        if (failures >= 2) {
          // the WebSocket can't get through (an old API or a proxy without WebSocket support): poll instead
          setMode('polling')
          void poll()
          return
        }
        timer = window.setTimeout(connect, opened ? 500 : 1500)
      }
    }
    connect()

    return () => {
      stop = true
      window.clearTimeout(timer)
      cancelAnimationFrame(raf)
      if (ws) {
        ws.onclose = null
        ws.close()
      }
    }
  }, [id])

  return { snap, samples, error, mode }
}
