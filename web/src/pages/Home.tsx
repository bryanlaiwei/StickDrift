import { useAuth } from '../auth'
import { GameArt, type ArtKind } from '../components/ui/GameArt'
import { Lantern } from '../components/ui/Lantern'
import { LobbyPreview } from '../components/ui/LobbyPreview'
import './Home.css'

interface Best {
  best: number
  stars: number
}

/** Games that can be played in the lobby today. The pictures are real captures of the 3D games. */
const PLAYABLE = [
  {
    id: 'apple',
    title: 'Apple Picking',
    blurb: 'Pick red and blue apples with the matching glove and drop them in the basket.',
    skill: 'Two-hand coordination',
    img: '/lobby/apple.jpg',
  },
  {
    id: 'fish',
    title: 'Harbour Fishing',
    blurb: 'Trace the glowing lane with the rod, one hand at a time, to reel the fish in.',
    skill: 'Smooth tracking',
    img: '/lobby/fish.jpg',
  },
  {
    id: 'rat',
    title: 'Rat Catching',
    blurb: 'Slam the hand down on the right rat as it runs past, and let the others go.',
    skill: 'Timing and restraint',
    img: '/lobby/rat.jpg',
  },
]

/** Mock-ups of games we want to add. They are not playable yet. */
const SOON: { id: string; kind: ArtKind; title: string; blurb: string; skill: string }[] = [
  {
    id: 'haunted',
    kind: 'haunted',
    title: 'Haunted House',
    blurb: 'Sweep a lantern through the dark rooms and flick to catch the friendly ghosts before they fade.',
    skill: 'Tracking and flicks',
  },
  {
    id: 'space',
    kind: 'space',
    title: 'Space Station',
    blurb: 'Steer two robot arms to sort glowing stars into the dock that matches their colour.',
    skill: 'Two-hand sorting',
  },
  {
    id: 'candy',
    kind: 'candy',
    title: 'Candy Factory',
    blurb: 'Grab the right sweet off a moving belt and let the wrong ones roll past.',
    skill: 'Reaction and restraint',
  },
]

/** High scores the lobby saves in this browser (same origin as the dashboard). */
function readBest(): Record<string, Best> {
  try {
    const db = JSON.parse(localStorage.getItem('stickdrift.lobby.scores.v1') ?? 'null')
    const mine = db?.players?.['player-1'] ?? Object.values(db?.players ?? {})[0] ?? {}
    return mine as Record<string, Best>
  } catch {
    return {}
  }
}

function Stars({ n }: { n: number }) {
  return (
    <span className="hm-stars" aria-label={`${n} of 3 stars`}>
      {[0, 1, 2].map((i) => (
        <span key={i} className={i < n ? 'on' : ''} aria-hidden>
          ★
        </span>
      ))}
    </span>
  )
}

export default function Home() {
  const { me } = useAuth()
  const best = readBest()

  return (
    <main className="wrap hm room">
      <header className="hm-head">
        <div className="hm-head-copy">
          <p className="eyebrow">Resident</p>
          <h1>Hi, {me?.display_name}.</h1>
          <p>Ready for a game today?</p>
        </div>
        <div className="hm-lamps dye-resident" aria-hidden>
          <Lantern shape="column" cord={26} delay={200}>
            <b>Play</b>
          </Lantern>
        </div>
      </header>

      <section className="hm-hero" aria-labelledby="hm-hero-title">
        <LobbyPreview />
        <div className="hm-hero-copy">
          <p className="hm-eyebrow">Game lobby</p>
          <h2 id="hm-hero-title">Walk the garden and pick a game</h2>
          <p className="hm-muted">
            Guide grandma to a glowing pad to play. When you are done, use the door at the edge of the garden to finish
            your visit.
          </p>
          <div className="hm-actions">
            <a className="stamp hm-btn" href="/lobby.html" target="_blank" rel="noopener noreferrer">
              Open the lobby
            </a>
            <span className="hm-note">Opens in a new tab · works best with a PS5 controller</span>
          </div>
        </div>
      </section>

      <section aria-labelledby="hm-play-title">
        <div className="hm-sec">
          <h2 id="hm-play-title">Ready to play</h2>
          <span>{PLAYABLE.length} games</span>
        </div>
        <div className="hm-grid">
          {PLAYABLE.map((g) => {
            const b = best[g.id]
            return (
              <article key={g.id} className="hm-card">
                <img src={g.img} alt="" loading="lazy" width={1280} height={720} />
                <div className="hm-card-body">
                  <h3>{g.title}</h3>
                  <p>{g.blurb}</p>
                  <div className="hm-meta">
                    <span className="hm-chip">{g.skill}</span>
                    {b?.best ? (
                      <span className="hm-best">
                        Best {b.best} <Stars n={b.stars} />
                      </span>
                    ) : (
                      <span className="hm-best hm-dim">Not played yet</span>
                    )}
                  </div>
                </div>
              </article>
            )
          })}
        </div>
      </section>

      <section aria-labelledby="hm-soon-title">
        <div className="hm-sec">
          <h2 id="hm-soon-title">Coming soon</h2>
          <span>Mock-ups, not playable yet</span>
        </div>
        <div className="hm-grid">
          {SOON.map((g) => (
            <article key={g.id} className="hm-card hm-soon" aria-disabled="true">
              <div className="hm-art">
                <GameArt kind={g.kind} />
                <span className="hm-ribbon">Coming soon</span>
              </div>
              <div className="hm-card-body">
                <h3>{g.title}</h3>
                <p>{g.blurb}</p>
                <div className="hm-meta">
                  <span className="hm-chip">{g.skill}</span>
                  <span className="hm-best hm-dim">In design</span>
                </div>
              </div>
            </article>
          ))}
        </div>
      </section>

      <footer className="hm-foot">
        Stick Drift helps care teams notice changes worth checking. It does not diagnose any condition. If someone has a
        sudden new symptom, follow your usual urgent-care procedure.
      </footer>
    </main>
  )
}
