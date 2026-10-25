import { useId, type CSSProperties, type ReactNode } from 'react'
import './lantern.css'

export type LanternShape = 'column' | 'moon'

/**
 * An akari: dyed washi stretched over bamboo ribs, lit from inside. Drawn as SVG so the ribs bow like paper under
 * light. The colours come from the dye class on a parent (.dye-resident / .dye-care, see styles/room.css). The light
 * is the state: dim until the page "switches it on", brighter when its door is hovered or focused.
 */
export function Lantern({
  shape,
  cord = 40,
  delay = 0,
  children,
}: {
  shape: LanternShape
  cord?: number
  delay?: number
  children?: ReactNode
}) {
  const id = useId().replace(/:/g, '')
  const column = shape === 'column'
  return (
    <div className={`lt lt-${shape}`} style={{ '--cord': `${cord}px`, '--delay': `${delay}ms` } as CSSProperties}>
      <span className="lt-spill" aria-hidden />
      <div className="lt-swing">
        <svg viewBox={column ? '0 0 240 400' : '0 0 320 340'} className="lt-svg" aria-hidden focusable="false">
          <defs>
            <radialGradient id={`${id}-paper`} cx="50%" cy="46%" r="68%">
              <stop offset="0" style={{ stopColor: 'var(--core)' }} />
              <stop offset="0.5" style={{ stopColor: 'var(--mid)' }} />
              <stop offset="1" style={{ stopColor: 'var(--edge)' }} />
            </radialGradient>
            <radialGradient id={`${id}-bulb`} cx="50%" cy="46%" r="46%">
              <stop offset="0" stopColor="#fffbe8" stopOpacity="0.95" />
              <stop offset="1" stopColor="#fffbe8" stopOpacity="0" />
            </radialGradient>
            <linearGradient id={`${id}-shade`} x1="0" x2="1" y1="0" y2="0">
              <stop offset="0" stopColor="#12081c" stopOpacity="0.5" />
              <stop offset="0.3" stopColor="#12081c" stopOpacity="0" />
              <stop offset="0.7" stopColor="#12081c" stopOpacity="0" />
              <stop offset="1" stopColor="#12081c" stopOpacity="0.55" />
            </linearGradient>
            <radialGradient id={`${id}-sphere`} cx="50%" cy="50%" r="50%">
              <stop offset="0.55" stopColor="#12081c" stopOpacity="0" />
              <stop offset="1" stopColor="#12081c" stopOpacity="0.55" />
            </radialGradient>
          </defs>
          {column ? (
            <>
              <path d="M120 0v46" className="lt-cord" />
              <path d="M24 56C24 40 216 40 216 56V346C216 366 24 366 24 346Z" fill={`url(#${id}-paper)`} />
              <path d="M24 56C24 40 216 40 216 56V346C216 366 24 366 24 346Z" fill={`url(#${id}-shade)`} />
              <ellipse cx="120" cy="56" rx="96" ry="12" className="lt-rib" />
              {[110, 160, 210, 260, 310].map((y) => (
                <path key={y} d={`M24 ${y}Q120 ${y + 16} 216 ${y}`} className="lt-rib" />
              ))}
              <path d="M24 346Q120 372 216 346" className="lt-rib" />
              <ellipse cx="120" cy="206" rx="120" ry="150" fill={`url(#${id}-bulb)`} className="lt-bulb" />
            </>
          ) : (
            <>
              <path d="M160 0v58" className="lt-cord" />
              <circle cx="160" cy="196" r="138" fill={`url(#${id}-paper)`} />
              <circle cx="160" cy="196" r="138" fill={`url(#${id}-sphere)`} />
              {[26, 62, 100, 130].map((rx) => (
                <ellipse key={rx} cx="160" cy="196" rx={rx} ry="138" className="lt-rib" />
              ))}
              <ellipse cx="160" cy="196" rx="138" ry="20" className="lt-rib" />
              <rect x="146" y="50" width="28" height="12" rx="3" className="lt-cap" />
              <circle cx="160" cy="196" r="150" fill={`url(#${id}-bulb)`} className="lt-bulb" />
            </>
          )}
        </svg>
        <div className="lt-label">{children}</div>
      </div>
    </div>
  )
}
