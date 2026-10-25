import { useState } from "react";
import type { ReachTrial } from "../../api";
import { pct, secs } from "../../format";
import { HANDS } from "./samples";

const TRIAL_TEXT: Record<string, { one: string; title: string; caption: string; empty: string }> = {
  apple: {
    one: "Apple",
    title: "Time to pick each apple",
    caption: "From the apple being free to pick until the glove grabs it. Lower is quicker.",
    empty: "Appears as apples are picked in Apple Picking.",
  },
  rat: {
    one: "Rat",
    title: "Time to slam each target rat",
    caption: "From the target rat appearing until the stick is flicked up to slam. Lower is quicker.",
    empty: "Appears as target rats run past in Rat Catching.",
  },
};

/** Attempts arrive one hand at a time; pair them up by game and number. */
function lobbyRows(trials: ReachTrial[], level: string | null | undefined): [ReachTrial[], string] {
  const games = trials.map((t) => t.game).filter((g): g is string => !!g);
  const game = level && games.includes(level) ? level : games[games.length - 1];
  const byNum = new Map<number, ReachTrial>();
  for (const t of trials) {
    if (t.game !== game) continue;
    byNum.set(t.trial, { ...byNum.get(t.trial), ...t });
  }
  return [[...byNum.values()], game ?? level ?? "apple"];
}

export function ReachTrialsChart({
  trials,
  level,
}: {
  trials: ReachTrial[];
  level?: string | null;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const [all, game] = lobbyRows(trials, level);
  const text = TRIAL_TEXT[game] ?? TRIAL_TEXT.apple;
  const rows = all.filter((t) => t.left || t.right);
  if (rows.length === 0)
    return <p className="muted">{text.empty}</p>;
  const vals = rows
    .flatMap((t) => HANDS.map((h) => t[h]?.reach_s ?? null))
    .filter((v): v is number => v != null);
  const max = Math.max(1, Math.ceil(Math.max(...vals, 0) * 2) / 2);
  const W = 640,
    H = 220,
    L = 44,
    B = 28,
    T = 10;
  const slot = (W - L - 8) / Math.max(rows.length, 6);
  const bw = Math.min(26, (slot - 10) / 2);
  const y = (v: number) => T + (H - T - B) * (1 - v / max);
  return (
    <figure className="live-fig">
      <figcaption>
        <strong>{text.title}</strong>
        <span className="muted">{text.caption}</span>
      </figcaption>
      <div className="chart-legend">
        <span className="chart-key">
          <span
            className="chart-swatch"
            style={{ background: "var(--hand-left)" }}
            aria-hidden
          />{" "}
          Left hand
        </span>
        <span className="chart-key">
          <span
            className="chart-swatch"
            style={{ background: "var(--hand-right)" }}
            aria-hidden
          />{" "}
          Right hand
        </span>
        <span className="chart-key">
          <span className="chart-ring chart-ring-muted" aria-hidden /> Not
          reached
        </span>
      </div>
      <div className="rolling-wrap">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="chart-svg"
          role="img"
          aria-label={`${text.title}, left and right hand`}
        >
          {[0, 0.25, 0.5, 0.75, 1].map((f) => (
            <g key={f}>
              <line
                className="chart-grid"
                x1={L}
                x2={W - 8}
                y1={y(max * f)}
                y2={y(max * f)}
              />
              <text
                className="chart-axis"
                x={L - 8}
                y={y(max * f)}
                textAnchor="end"
                dominantBaseline="middle"
              >
                {(max * f).toFixed(1)}s
              </text>
            </g>
          ))}
          {rows.map((t, i) => {
            const cx = L + slot * i + slot / 2;
            return (
              <g
                key={`${t.game ?? ''}-${t.trial}`}
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
              >
                <rect
                  x={cx - slot / 2}
                  y={T}
                  width={slot}
                  height={H - T - B}
                  fill="transparent"
                />
                {HANDS.map((h, k) => {
                  const r = t[h];
                  const bx = cx + (k === 0 ? -bw - 1 : 1);
                  if (!r) return null;
                  if (r.reach_s == null)
                    return (
                      <circle
                        key={h}
                        cx={bx + bw / 2}
                        cy={y(0) - 8}
                        r={5}
                        className="miss-ring"
                      />
                    );
                  const top = y(r.reach_s);
                  return (
                    <path
                      key={h}
                      d={`M${bx} ${y(0)} V${top + 4} Q${bx} ${top} ${bx + 4} ${top} H${bx + bw - 4} Q${bx + bw} ${top} ${bx + bw} ${top + 4} V${y(0)} Z`}
                      style={{ fill: `var(--hand-${h})` }}
                    />
                  );
                })}
                <text
                  className="chart-axis"
                  x={cx}
                  y={H - 8}
                  textAnchor="middle"
                >
                  {t.trial}
                </text>
              </g>
            );
          })}
        </svg>
        {hover != null && (
          <div className="live-tip" role="tooltip">
            <strong>
              {text.one} {rows[hover].trial}
            </strong>
            {HANDS.map((h) => {
              const r = rows[hover][h];
              return r ? (
                <span key={h}>
                  <i style={{ background: `var(--hand-${h})` }} />{" "}
                  {h === "left" ? "Left" : "Right"}:{" "}
                  {r.reach_s == null ? "not reached" : secs(r.reach_s)} ·
                  reaction {secs(r.reaction_s)} · stick push {pct(r.reach_size)}
                </span>
              ) : null;
            })}
          </div>
        )}
      </div>
    </figure>
  );
}
