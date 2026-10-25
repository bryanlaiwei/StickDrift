import { useState } from 'react'
import { handReplayUrl, type HandReplayInfo } from '../../api'
import { levelName } from '../../labels'

function windowText(info: HandReplayInfo | null | undefined) {
  if (!info) return null
  const parts = [levelName(info.game), info.duration_s ? `${Math.round(info.duration_s)} s` : null]
  return parts.filter(Boolean).join(', ') || null
}

function altText(info: HandReplayInfo | null | undefined, name?: string) {
  const who = name ? `${name}’s hands` : 'The resident’s hands'
  const when = info?.game ? ` during ${levelName(info.game)}` : ''
  const shake =
    info?.has_motion === false
      ? 'The controller’s motion sensor was off, so hand shake is not shown.'
      : 'Hand shake from the controller’s motion sensor is drawn 10 times larger.'
  return (
    `Animated reconstruction of ${who} holding the controller${when}. The thumbs follow the recorded sticks. ` +
    `${shake} Red wrist cuff: left hand. Blue wrist cuff: right hand.`
  )
}

/**
 * One visit's reconstructed hands: a short looping GIF of the 3D hands and controller (ml/hand_replay/).
 * `pending` shows a quiet placeholder while the GIF is still being drawn; a missing GIF shows nothing.
 */
export function HandReplay({
  sessionId,
  info,
  name,
  pending = false,
}: {
  sessionId?: string | null
  info?: HandReplayInfo | null
  name?: string
  pending?: boolean
}) {
  const [missing, setMissing] = useState(false)
  if (missing) return null
  const where = windowText(info)

  if (pending || !sessionId) {
    return (
      <figure className="hand-replay">
        <div className="hand-replay-frame hand-replay-wait" aria-hidden />
        <figcaption>
          <strong>Reconstructed hands</strong>
          <span className="muted">Drawing the hands from this visit…</span>
        </figcaption>
      </figure>
    )
  }

  return (
    <figure className="hand-replay">
      <div className="hand-replay-frame">
        <img
          src={handReplayUrl(sessionId)}
          loading="lazy"
          width={400}
          height={300}
          alt={altText(info, name)}
          onError={() => setMissing(true)}
        />
      </div>
      <figcaption>
        <strong>Reconstructed hands, shake drawn ×10</strong>
        {where && <span className="muted">{where}</span>}
        {info?.has_motion === false && <span className="hint">No motion sensor: shake not shown</span>}
      </figcaption>
    </figure>
  )
}
