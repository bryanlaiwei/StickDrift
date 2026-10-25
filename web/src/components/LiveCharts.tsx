import { useEffect, useRef, useState } from "react";
import type {
  LiveMetrics,
  LiveSample,
  PatternScores,
  RatReport,
  ReachTrial,
  TcnLevel,
} from "../api";
import {
  HANDS,
  HZ,
  PATTERN_HINTS,
  PATTERN_LABELS,
  PATTERN_ORDER,
  handCursor,
  handPoint,
  handPos as stickPos,
  handTarget,
  levelName,
  pct,
  secs,
  type Hand,
} from "./liveData";

function cssVar(name: string) {
  return (
    getComputedStyle(document.documentElement).getPropertyValue(name).trim() ||
    "#888"
  );
}

/** Canvas sized to its box at device pixel ratio; redraws when the box or `deps` change. */
function useCanvas(
  draw: (ctx: CanvasRenderingContext2D, w: number, h: number) => void,
  deps: unknown[],
) {
  const ref = useRef<HTMLCanvasElement>(null);
  const drawRef = useRef(draw);
  drawRef.current = draw;
  const [size, setSize] = useState({ w: 0, h: 0 });

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize({ w: Math.round(width), h: Math.round(height) });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const el = ref.current;
    if (!el || !size.w || !size.h) return;
    const dpr = window.devicePixelRatio || 1;
    el.width = size.w * dpr;
    el.height = size.h * dpr;
    const ctx = el.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size.w, size.h);
    drawRef.current(ctx, size.w, size.h);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [size, ...deps]);

  return ref;
}

// ---- live stick fields ------------------------------------------------------

export function StickFields({ samples }: { samples: LiveSample[] }) {
  const trail = samples.slice(-Math.round(HZ * 1.5));
  const last = trail[trail.length - 1];
  // Games that steer a hand: draw that hand, not the stick. Rat Catching has none, so it shows sticks.
  const inGame = !!last && HANDS.some((hd) => handCursor(last, hd));
  const handPos = inGame ? handPoint : stickPos;
  const ref = useCanvas(
    (ctx, w, h) => {
      const ink = cssVar("--muted");
      const line = cssVar("--line");
      const r = Math.min(w / 4, h / 2) - 18;
      HANDS.forEach((hand, i) => {
        const cx = (w / 4) * (i === 0 ? 1 : 3);
        const cy = h / 2;
        const color = cssVar(hand === "left" ? "--hand-left" : "--hand-right");
        ctx.strokeStyle = line;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(cx - 6, cy);
        ctx.lineTo(cx + 6, cy);
        ctx.moveTo(cx, cy - 6);
        ctx.lineTo(cx, cy + 6);
        ctx.stroke();
        ctx.fillStyle = ink;
        ctx.font = "600 13px system-ui, sans-serif";
        ctx.textAlign = "center";
        ctx.fillText(
          inGame ? (hand === "left" ? "Left hand (in game)" : "Right hand (in game)") : hand === "left" ? "Left stick" : "Right stick",
          cx,
          h - 4,
        );
        if (!last) return;
        const target = handTarget(last, hand);
        if (target) {
          ctx.strokeStyle = ink;
          ctx.setLineDash([4, 4]);
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.arc(
            cx + target[0] * r,
            cy + target[1] * r,
            0.2 * r,
            0,
            Math.PI * 2,
          );
          ctx.stroke();
          ctx.setLineDash([]);
        }
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.globalAlpha = 0.45;
        ctx.beginPath();
        trail.forEach((s, k) => {
          const [x, y] = handPos(s, hand);
          if (k === 0) ctx.moveTo(cx + x * r, cy + y * r);
          else ctx.lineTo(cx + x * r, cy + y * r);
        });
        ctx.stroke();
        ctx.globalAlpha = 1;
        const [x, y] = handPos(last, hand);
        ctx.fillStyle = color;
        ctx.strokeStyle = cssVar("--surface");
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(cx + x * r, cy + y * r, 8, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
      });
    },
    [last?.[0]],
  );
  return (
    <figure className="live-fig">
      <canvas
        ref={ref}
        className="stick-fields"
        role="img"
        aria-label="Live position of each stick and its current target. Dashed rings are targets."
      />
      <figcaption className="muted">
        {inGame
          ? "Dot = where the stick has steered the hand · faint line = last 1.5 s · dashed ring = the target"
          : "Dot = stick now · faint line = last 1.5 s · dashed ring = where the game wants it"}
      </figcaption>
    </figure>
  );
}

// ---- rolling line chart -----------------------------------------------------

interface RollingProps {
  title: string;
  caption: string;
  samples: LiveSample[];
  windowS: number;
  value: (s: LiveSample, hand: Hand) => number | null;
  max: number;
  format: (v: number) => string;
}

export function RollingChart({
  title,
  caption,
  samples,
  windowS,
  value,
  max,
  format,
}: RollingProps) {
  const [hover, setHover] = useState<number | null>(null);
  const pad = { l: 48, r: 12, t: 10, b: 24 };
  const lastSeq = samples.length ? samples[samples.length - 1][0] : 0;
  const first = lastSeq - windowS * HZ;
  const view = samples.filter((s) => s[0] > first);

  const ref = useCanvas(
    (ctx, w, h) => {
      const pw = w - pad.l - pad.r;
      const ph = h - pad.t - pad.b;
      const x = (seq: number) => pad.l + ((seq - first) / (windowS * HZ)) * pw;
      const y = (v: number) => pad.t + ph * (1 - Math.min(v, max) / max);
      ctx.font = "12px system-ui, sans-serif";
      ctx.fillStyle = cssVar("--muted");
      ctx.strokeStyle = cssVar("--line");
      ctx.lineWidth = 1;
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      for (let k = 0; k <= 4; k++) {
        const v = (max * k) / 4;
        ctx.beginPath();
        ctx.moveTo(pad.l, y(v));
        ctx.lineTo(w - pad.r, y(v));
        ctx.stroke();
        ctx.fillText(format(v), pad.l - 8, y(v));
      }
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      for (let k = 0; k <= windowS; k += 5) {
        const sx = pad.l + (k / windowS) * pw;
        ctx.fillText(
          k === windowS ? "now" : `−${windowS - k}s`,
          sx,
          h - pad.b + 6,
        );
      }
      // Game boundaries.
      ctx.strokeStyle = cssVar("--muted");
      ctx.setLineDash([3, 4]);
      for (let k = 1; k < view.length; k++) {
        if (view[k][1] !== view[k - 1][1]) {
          ctx.beginPath();
          ctx.moveTo(x(view[k][0]), pad.t);
          ctx.lineTo(x(view[k][0]), h - pad.b);
          ctx.stroke();
        }
      }
      ctx.setLineDash([]);
      for (const hand of HANDS) {
        ctx.strokeStyle = cssVar(
          hand === "left" ? "--hand-left" : "--hand-right",
        );
        ctx.lineWidth = 2;
        ctx.lineJoin = "round";
        ctx.beginPath();
        let pen = false;
        let prev = -1;
        for (const s of view) {
          const v = value(s, hand);
          if (v == null || s[0] !== prev + 1) pen = false;
          prev = s[0];
          if (v == null) continue;
          if (pen) ctx.lineTo(x(s[0]), y(v));
          else ctx.moveTo(x(s[0]), y(v));
          pen = true;
        }
        ctx.stroke();
      }
      if (hover != null) {
        ctx.strokeStyle = cssVar("--ink");
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x(hover), pad.t);
        ctx.lineTo(x(hover), h - pad.b);
        ctx.stroke();
      }
    },
    [lastSeq, hover],
  );

  const hovered = hover == null ? null : view.find((s) => s[0] >= hover);
  const onMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const frac = (e.clientX - rect.left - pad.l) / (rect.width - pad.l - pad.r);
    setHover(
      frac < 0 || frac > 1 || !view.length
        ? null
        : Math.round(first + frac * windowS * HZ),
    );
  };

  return (
    <figure className="live-fig">
      <figcaption>
        <strong>{title}</strong>
        <span className="muted">{caption}</span>
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
          <span className="chart-dash" aria-hidden /> New game
        </span>
      </div>
      <div className="rolling-wrap">
        <canvas
          ref={ref}
          className="rolling"
          onMouseMove={onMove}
          onMouseLeave={() => setHover(null)}
          role="img"
          aria-label={`${title}, last ${windowS} seconds`}
        />
        {hovered && (
          <div className="live-tip" role="tooltip">
            <strong>{((lastSeq - hovered[0]) / HZ).toFixed(1)} s ago</strong>
            {HANDS.map((hand) => {
              const v = value(hovered, hand);
              return (
                <span key={hand}>
                  <i style={{ background: `var(--hand-${hand})` }} />{" "}
                  {hand === "left" ? "Left" : "Right"}:{" "}
                  {v == null ? "—" : format(v)}
                </span>
              );
            })}
          </div>
        )}
      </div>
    </figure>
  );
}

// ---- apple-by-apple bars ------------------------------------------------------

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

// ---- left-right difference ----------------------------------------------------

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

// ---- end of a lobby visit ---------------------------------------------------------

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

export function hasPatternScores(scores: PatternScores | null | undefined) {
  return !!scores && PATTERN_ORDER.some((k) => scores[k] != null);
}

// ---- TCN pattern judgement --------------------------------------------------------

export function PatternBars({
  scores,
  levels,
}: {
  scores: PatternScores;
  levels?: TcnLevel[];
}) {
  return (
    <div className="patterns">
      <ul className="pattern-list">
        {PATTERN_ORDER.map((k) => {
          const v = scores[k];
          const level =
            v == null ? null : v >= 70 ? "check" : v >= 50 ? "watch" : null;
          return (
            <li key={k}>
              <span className="pattern-label">
                {PATTERN_LABELS[k]}
                <small className="pattern-hint">{PATTERN_HINTS[k]}</small>
              </span>
              <span className="pattern-track" aria-hidden>
                <span
                  className="pattern-fill"
                  style={{ width: `${v ?? 0}%` }}
                />
                <span className="pattern-mark" style={{ left: "50%" }} />
                <span className="pattern-mark" style={{ left: "70%" }} />
              </span>
              <span className="pattern-val num">
                {v == null ? "n/a" : `${Math.round(v)}/100`}
              </span>
              {level ? (
                <span className={`risk-badge risk-${level}`}>
                  {level === "check" ? "Check soon" : "Keep an eye on"}
                </span>
              ) : (
                <span className="pattern-ok muted">
                  {v == null ? "" : "Low"}
                </span>
              )}
            </li>
          );
        })}
      </ul>
      {levels && levels.length > 0 && (
        <details className="pattern-levels">
          <summary>Scores by game</summary>
          <table>
            <thead>
              <tr>
                <th scope="col">Game</th>
                {PATTERN_ORDER.map((k) => (
                  <th scope="col" key={k}>
                    {PATTERN_LABELS[k]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {levels.map((lv) => (
                <tr key={lv.level}>
                  <td>{levelName(lv.level)}</td>
                  {PATTERN_ORDER.map((k) => (
                    <td key={k} className="num">
                      {lv.scores[k] == null
                        ? "—"
                        : Math.round(lv.scores[k] as number)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
      <p className="hint">
        0–100 resemblance to each movement pattern, judged by the TCN model at
        the end of the session. Tick marks show the 50 (keep an eye on) and 70
        (check soon) lines. This is not a diagnosis.
      </p>
    </div>
  );
}
