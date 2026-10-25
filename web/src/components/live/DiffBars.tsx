import type { LiveMetrics } from "../../api";

const DIFF_ROWS: {
  key: keyof LiveMetrics["hands"]["left"];
  label: string;
  more: string;
}[] = [
  { key: "reaction_s", label: "Reaction time", more: "slower to start" },
  { key: "reach_s", label: "Time to reach", more: "slower to reach" },
  { key: "peak_speed", label: "Peak speed", more: "faster" },
  { key: "reach_size", label: "Reach size", more: "bigger reaches" },
  {
    key: "tracking_error",
    label: "Distance from target",
    more: "further off target",
  },
  { key: "shake", label: "Shake", more: "shakier" },
];

export function DiffBars({
  diff,
}: {
  diff: LiveMetrics["left_right_difference_pct"];
}) {
  const rows = DIFF_ROWS.filter((r) => diff[r.key] != null);
  if (rows.length === 0)
    return <p className="muted">Appears once both hands have been measured.</p>;
  return (
    <ul className="diff-list">
      {rows.map((r) => {
        const v = diff[r.key] as number;
        const width = Math.min(Math.abs(v), 100) / 2;
        const side = v >= 0 ? "left" : "right";
        const small = Math.abs(v) < 10;
        return (
          <li key={r.key}>
            <span className="diff-label">{r.label}</span>
            <span className="diff-track" aria-hidden>
              <span className="diff-mid" />
              <span
                className="diff-bar"
                style={{
                  width: `${width}%`,
                  [v >= 0 ? "right" : "left"]: "50%",
                  background: `var(--hand-${side})`,
                }}
              />
            </span>
            <span className="diff-text">
              {small
                ? "About even"
                : `${side === "left" ? "Left" : "Right"} ${Math.abs(v).toFixed(0)}% ${r.more}`}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
