import { useState } from "react";
import type { LiveSample } from "../../api";
import { cssVar, useCanvas } from "./canvas";
import { HANDS, HZ, type Hand } from "./samples";

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
