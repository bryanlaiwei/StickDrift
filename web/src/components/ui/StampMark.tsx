/** The Stick Drift mark as a hanko stamp: two thumbsticks cut out of a vermilion block. */
export function StampMark({ size = 64, decorative = false }: { size?: number; decorative?: boolean }) {
  return (
    <svg
      viewBox="0 0 64 64"
      width={size}
      height={size}
      role={decorative ? undefined : 'img'}
      aria-label={decorative ? undefined : 'Stick Drift'}
      aria-hidden={decorative || undefined}
      className="stamp-mark"
    >
      <rect x="2" y="2" width="60" height="60" rx="9" fill="#d93a2b" />
      <rect x="7" y="7" width="50" height="50" rx="5" fill="none" stroke="#fff3ea" strokeOpacity="0.55" strokeWidth="2" />
      <circle cx="22" cy="34" r="9" fill="#fff3ea" />
      <circle cx="42" cy="34" r="9" fill="#fff3ea" />
      <circle cx="24.5" cy="31" r="3.4" fill="#d93a2b" />
      <circle cx="44.5" cy="37" r="3.4" fill="#d93a2b" />
    </svg>
  )
}
