import { useEffect, useRef, useState } from "react";

/** A CSS custom property's current value (theme colours), with a grey fallback. */
export function cssVar(name: string) {
  return (
    getComputedStyle(document.documentElement).getPropertyValue(name).trim() ||
    "#888"
  );
}

/** Canvas sized to its box at device pixel ratio; redraws when the box or `deps` change. */
export function useCanvas(
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
