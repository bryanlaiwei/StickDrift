import { Link } from 'react-router'
import { GameStrip } from '../components/ui/GameStrip'
import { Lantern } from '../components/ui/Lantern'
import { StampMark } from '../components/ui/StampMark'
import { useNightRoom } from '../components/ui/useNightRoom'
import '../styles/room.css'
import './Welcome.css'

/** One door: a lantern you walk up to. The stamp is the link; its hit area stretches over the whole door. */
function Door({
  dye,
  shape,
  cord,
  delay,
  name,
  line,
  to,
  action,
  altTo,
  alt,
}: {
  dye: 'resident' | 'care'
  shape: 'column' | 'moon'
  cord: number
  delay: number
  name: string
  line: string
  to: string
  action: string
  altTo: string
  alt: string
}) {
  return (
    <div className={`door dye-${dye}`}>
      <Lantern shape={shape} cord={cord} delay={delay}>
        <b>{name}</b>
        <small>{line}</small>
      </Lantern>
      <div className="door-actions">
        <Link className="stamp door-link" to={to}>
          {action}
        </Link>
        <Link className="door-alt" to={altTo}>
          {alt}
        </Link>
      </div>
    </div>
  )
}

export default function Welcome() {
  useNightRoom()
  return (
    <main className="room welcome">
      <section className="wc-hero">
        <div className="wc-copy">
          <StampMark size={72} />
          <h1>Games you play with two thumbs.</h1>
          <p>
            Short games for a PS5 controller, with one stick for each hand. Pick one and play at your own pace. Your care
            team can see how each visit went.
          </p>
        </div>

        <div className="wc-doors">
          <Door
            dye="resident"
            shape="column"
            cord={36}
            delay={300}
            name="Resident"
            line="I’m here to play"
            to="/login"
            action="Resident log in"
            altTo="/signup"
            alt="New here? Create an account"
          />
          <Door
            dye="care"
            shape="moon"
            cord={150}
            delay={900}
            name="Care team"
            line="I look after residents"
            to="/caregiver/login"
            action="Care team log in"
            altTo="/caregiver/signup"
            alt="New to the team? Register"
          />
        </div>
      </section>

      <section className="wc-games" aria-labelledby="wc-games-title">
        <h2 id="wc-games-title">Three games to start</h2>
        <GameStrip />
      </section>

      <p className="wc-note">
        Stick Drift helps care teams notice changes worth checking. It does not diagnose any condition. If someone has a
        sudden new symptom, follow your usual urgent-care procedure.
      </p>
    </main>
  )
}
