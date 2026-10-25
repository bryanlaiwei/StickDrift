// Illustrations for the games that are still on the drawing board. Each has its own palette and mood so the lobby
// feels like more than the garden: a haunted house, a space station and a candy factory.

export type ArtKind = 'haunted' | 'space' | 'candy'

function Haunted() {
  return (
    <svg viewBox="0 0 320 180" preserveAspectRatio="xMidYMid slice" aria-hidden>
      <defs>
        <linearGradient id="hh-sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#140c2b" />
          <stop offset="1" stopColor="#3b2160" />
        </linearGradient>
        <radialGradient id="hh-moon" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#fff6cf" />
          <stop offset="1" stopColor="#fff6cf" stopOpacity="0" />
        </radialGradient>
      </defs>
      <rect width="320" height="180" fill="url(#hh-sky)" />
      <circle cx="252" cy="44" r="40" fill="url(#hh-moon)" />
      <circle cx="252" cy="44" r="19" fill="#fff3c4" />
      {[[30, 24], [70, 52], [120, 18], [168, 40], [206, 20], [292, 92], [18, 90]].map(([x, y]) => (
        <circle key={`${x}-${y}`} cx={x} cy={y} r="1.4" fill="#e9e2ff" opacity="0.8" />
      ))}
      <path d="M0 150 Q80 128 160 142 T320 134 V180 H0Z" fill="#1d1236" />
      {/* the house */}
      <g fill="#0e0820">
        <rect x="92" y="78" width="110" height="74" />
        <path d="M84 80 L147 40 L210 80Z" />
        <rect x="170" y="48" width="14" height="30" />
        <rect x="104" y="58" width="10" height="24" />
        <path d="M100 58 L109 44 L118 58Z" />
      </g>
      {[[108, 92], [140, 92], [172, 92], [124, 122], [160, 122]].map(([x, y]) => (
        <rect key={`${x}-${y}`} x={x} y={y} width="16" height="20" rx="2" fill="#ffc857" opacity={x === 140 ? 1 : 0.85} />
      ))}
      <rect x="140" y="120" width="16" height="32" rx="2" fill="#2a1747" />
      {/* a bare tree */}
      <g stroke="#0e0820" strokeWidth="4" strokeLinecap="round" fill="none">
        <path d="M44 156 V108" />
        <path d="M44 124 L26 108 M44 116 L62 98 M44 134 L28 126" strokeWidth="3" />
      </g>
      {/* ghosts */}
      <g fill="#f4f1ff">
        <path d="M232 112 q0-24 16-24 t16 24 v28 l-8-6 -8 6 -8-6 -8 6Z" opacity="0.95" />
        <path d="M44 66 q0-14 10-14 t10 14 v18 l-5-4 -5 4 -5-4 -5 4Z" opacity="0.75" />
      </g>
      <g fill="#2a1747">
        <circle cx="242" cy="104" r="2.6" />
        <circle cx="254" cy="104" r="2.6" />
        <ellipse cx="248" cy="113" rx="3" ry="4" />
        <circle cx="50" cy="62" r="1.6" />
        <circle cx="58" cy="62" r="1.6" />
      </g>
      {/* bats and a pumpkin */}
      <g fill="#0e0820">
        <path d="M190 30 q8-10 16 0 q-8-3-16 0Z" />
        <path d="M120 70 q6-8 12 0 q-6-2-12 0Z" />
      </g>
      <circle cx="270" cy="150" r="11" fill="#f08a24" />
      <path d="M270 139 v-5" stroke="#3b7a2a" strokeWidth="3" strokeLinecap="round" />
      <path d="M264 148 l3 4 3-4 3 4 3-4" stroke="#7a3a00" strokeWidth="1.6" fill="none" strokeLinecap="round" />
      <path d="M0 160 Q70 148 140 160 T320 156 V180 H0Z" fill="#8c7ab8" opacity="0.25" />
    </svg>
  )
}

function Space() {
  return (
    <svg viewBox="0 0 320 180" preserveAspectRatio="xMidYMid slice" aria-hidden>
      <defs>
        <linearGradient id="sp-bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#050b24" />
          <stop offset="1" stopColor="#1a1f5c" />
        </linearGradient>
        <radialGradient id="sp-planet" cx="0.35" cy="0.35" r="0.8">
          <stop offset="0" stopColor="#ffb48a" />
          <stop offset="1" stopColor="#b8456b" />
        </radialGradient>
      </defs>
      <rect width="320" height="180" fill="url(#sp-bg)" />
      {[[22, 20], [54, 120], [90, 36], [140, 150], [188, 24], [226, 98], [296, 30], [300, 150], [110, 84], [262, 60], [12, 160]].map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r={i % 3 === 0 ? 1.8 : 1.1} fill="#fff" opacity={0.5 + (i % 4) * 0.12} />
      ))}
      <g transform="translate(236 118)">
        <circle r="34" fill="url(#sp-planet)" />
        <ellipse rx="54" ry="11" fill="none" stroke="#ffd9b3" strokeWidth="5" opacity="0.8" transform="rotate(-18)" />
        <path d="M-34 0 a34 34 0 0 0 68 0" fill="#000" opacity="0.18" />
      </g>
      {/* the station */}
      <g transform="translate(96 78) rotate(-12)">
        <rect x="-70" y="-6" width="46" height="12" rx="2" fill="#2f6df0" />
        <rect x="24" y="-6" width="46" height="12" rx="2" fill="#2f6df0" />
        <g stroke="#9bb8ff" strokeWidth="1">
          <path d="M-58 -6 v12 M-46 -6 v12 M-34 -6 v12 M36 -6 v12 M48 -6 v12 M60 -6 v12" />
        </g>
        <rect x="-24" y="-3" width="48" height="6" fill="#aab4c8" />
        <rect x="-16" y="-20" width="32" height="40" rx="9" fill="#e6ebf5" />
        <circle cy="0" r="9" fill="#27365f" />
        <circle cy="0" r="5" fill="#7fd6ff" />
        <rect x="-3" y="-30" width="6" height="12" rx="2" fill="#aab4c8" />
        <circle cy="-32" r="3" fill="#ff5d6c" />
      </g>
      {/* a little satellite and a comet */}
      <g transform="translate(40 142) rotate(20)">
        <rect x="-5" y="-5" width="10" height="10" fill="#ffd24a" />
        <rect x="-18" y="-3" width="10" height="6" fill="#4f8cff" />
        <rect x="8" y="-3" width="10" height="6" fill="#4f8cff" />
      </g>
      <path d="M280 20 L236 46" stroke="#bfe6ff" strokeWidth="2.5" strokeLinecap="round" opacity="0.7" />
      <circle cx="282" cy="19" r="4" fill="#fff" />
    </svg>
  )
}

function Candy() {
  return (
    <svg viewBox="0 0 320 180" preserveAspectRatio="xMidYMid slice" aria-hidden>
      <defs>
        <linearGradient id="cd-bg" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ffd6ec" />
          <stop offset="1" stopColor="#c9f5e4" />
        </linearGradient>
      </defs>
      <rect width="320" height="180" fill="url(#cd-bg)" />
      {/* lollipops */}
      <g>
        <rect x="42" y="52" width="5" height="60" rx="2.5" fill="#fff" />
        <circle cx="44.5" cy="42" r="22" fill="#ff5fa2" />
        <path d="M44.5 42 m-16 0 a16 16 0 1 1 32 0 a11 11 0 1 0 -22 0 a6 6 0 1 1 12 0" fill="none" stroke="#fff" strokeWidth="3.2" strokeLinecap="round" />
        <rect x="270" y="40" width="5" height="52" rx="2.5" fill="#fff" />
        <circle cx="272.5" cy="32" r="18" fill="#6fd3ff" />
        <path d="M272.5 32 m-12 0 a12 12 0 1 1 24 0 a8 8 0 1 0 -16 0" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" />
      </g>
      {/* factory chimney + gears */}
      <rect x="150" y="30" width="30" height="62" fill="#ff9ec7" />
      <rect x="146" y="24" width="38" height="10" rx="3" fill="#ff7ab4" />
      <g fill="#fff" opacity="0.9">
        <circle cx="156" cy="12" r="6" />
        <circle cx="170" cy="6" r="8" />
        <circle cx="186" cy="10" r="5" />
      </g>
      {/* conveyor belt */}
      <rect x="0" y="116" width="320" height="22" fill="#5b4a8a" />
      <rect x="0" y="136" width="320" height="8" fill="#3d3163" />
      <g fill="#7d6bb3">
        {Array.from({ length: 16 }, (_, i) => <rect key={i} x={i * 22 + 4} y="121" width="12" height="4" rx="2" />)}
      </g>
      {[[28, 148], [96, 148], [164, 148], [232, 148], [292, 148]].map(([x, y]) => <circle key={x} cx={x} cy={y} r="9" fill="#8a76c4" stroke="#3d3163" strokeWidth="3" />)}
      {/* candies riding the belt */}
      <g>
        <circle cx="70" cy="104" r="11" fill="#ffd24a" />
        <path d="M62 104 h16" stroke="#fff" strokeWidth="2.5" opacity="0.8" />
        <g transform="translate(120 105)">
          <ellipse rx="10" ry="8" fill="#4ad7a8" />
          <path d="M-10 0 l-9 -7 v14Z M10 0 l9 -7 v14Z" fill="#4ad7a8" />
        </g>
        <rect x="178" y="94" width="20" height="20" rx="5" fill="#ff6a6a" />
        <path d="M184 100 l8 8 M192 100 l-8 8" stroke="#fff" strokeWidth="2" opacity="0.8" />
        <g transform="translate(236 105)">
          <ellipse rx="10" ry="8" fill="#a78bff" />
          <path d="M-10 0 l-9 -7 v14Z M10 0 l9 -7 v14Z" fill="#a78bff" />
        </g>
      </g>
      {/* sprinkles */}
      {[[100, 40, 20, '#ff5fa2'], [208, 56, -30, '#4ad7a8'], [126, 62, 60, '#ffd24a'], [230, 30, 10, '#6fd3ff'], [80, 84, -50, '#a78bff'], [300, 96, 40, '#ff5fa2'], [14, 96, 25, '#4ad7a8']].map(([x, y, r, c]) => (
        <rect key={`${x}-${y}`} x={Number(x)} y={Number(y)} width="9" height="3.4" rx="1.7" fill={String(c)} transform={`rotate(${r} ${x} ${y})`} />
      ))}
    </svg>
  )
}

export function GameArt({ kind }: { kind: ArtKind }) {
  return kind === 'haunted' ? <Haunted /> : kind === 'space' ? <Space /> : <Candy />
}
