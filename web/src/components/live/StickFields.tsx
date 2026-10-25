import type { LiveSample } from "../../api";
import { cssVar, useCanvas } from "./canvas";
import { HANDS, HZ, handCursor, handPoint, handPos as stickPos, handTarget } from "./samples";

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
