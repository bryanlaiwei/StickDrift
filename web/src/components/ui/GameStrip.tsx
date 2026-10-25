import './gamestrip.css'

const GAMES = [
  { name: 'Apple Picking', text: 'Two gloves, two hands. Pick the apple that matches.', img: '/lobby/apple.jpg', pos: '48% 55%' },
  { name: 'Harbour Fishing', text: 'Follow the glowing line with the rod, one hand at a time.', img: '/lobby/fish.jpg', pos: '50% 60%' },
  { name: 'Rat Catching', text: 'Flick a stick to slam the hand on the right rat.', img: '/lobby/rat.jpg', pos: '38% 50%' },
]

/** Three games as paper panels folded flat against the wall. Each is lit from behind when you point at it. */
export function GameStrip() {
  return (
    <ul className="fold">
      {GAMES.map((g) => (
        <li key={g.name} tabIndex={0}>
          <div className="fold-pane">
            <img src={g.img} alt="" loading="lazy" width={1280} height={720} style={{ objectPosition: g.pos }} />
            <span className="fold-ribs" aria-hidden />
          </div>
          <div className="fold-text">
            <h3>{g.name}</h3>
            <p>{g.text}</p>
          </div>
        </li>
      ))}
    </ul>
  )
}
