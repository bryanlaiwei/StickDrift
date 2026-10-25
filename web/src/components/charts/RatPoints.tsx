import type { RatReport } from "../../api";

/** The points the resident earned in Rat Catching. The pattern model does not score that game. */
export function RatPoints({ rat, labeled = true }: { rat: RatReport; labeled?: boolean }) {
  if (rat.score == null) return null;
  const stars = rat.stars;
  return (
    <p className="visit-score">
      {labeled && <span className="visit-score-kicker">Rat Catching</span>}
      <strong>{rat.score}</strong>
      <span>
        points
        {stars != null ? ` · ${stars} ${stars === 1 ? "star" : "stars"}` : ""}
      </span>
    </p>
  );
}
