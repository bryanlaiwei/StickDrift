import { useEffect, useRef, useState } from 'react'

/**
 * The dashboard's picture of the lobby. A real screen capture of the 3D lobby shows straight away, then a live
 * three.js render of the same scene (grandma strolling between the game pads) fades in on top. The three.js code is
 * loaded on demand so the dashboard itself stays light; without WebGL the still stays.
 */
export function LobbyPreview() {
  const canvas = useRef<HTMLCanvasElement>(null)
  const [live, setLive] = useState(false)

  useEffect(() => {
    let cancelled = false
    let dispose: (() => void) | undefined
    import('../../../lobby/preview.js')
      .then(({ mountPreview }) => {
        if (cancelled || !canvas.current) return
        try {
          dispose = mountPreview(canvas.current, { onFrame: () => setLive(true) }).dispose
        } catch {
          /* no WebGL: keep showing the still */
        }
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
      dispose?.()
    }
  }, [])

  return (
    <div className="lp" role="img" aria-label="Live view of the game lobby: a garden with three game pads and a grandmother walking between them">
      <img className="lp-still" src="/lobby/lobby.jpg" alt="" width={1280} height={720} />
      <canvas ref={canvas} className={`lp-canvas${live ? ' is-live' : ''}`} aria-hidden />
      <span className={`lp-badge${live ? ' is-live' : ''}`}>
        <i aria-hidden /> {live ? 'Live' : 'Preview'}
      </span>
    </div>
  )
}
