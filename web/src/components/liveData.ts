import type { LiveSample, PatternKey } from "../api";

// Sample columns: [seq, level, t, trial, phase, lx, ly, rx, ry, tlx, tly, trx, try, reached_l, reached_r]
export const LX = 5,
  LY = 6,
  RX = 7,
  RY = 8,
  TLX = 9,
  TLY = 10,
  TRX = 11,
  TRY = 12,
  CLX = 15;
export const HZ = 100;

export type Hand = "left" | "right";
export const HANDS: Hand[] = ["left", "right"];

export function handPos(s: LiveSample, hand: Hand): [number, number] {
  return hand === "left" ? [s[LX], s[LY]] : [s[RX], s[RY]];
}

export function handTarget(s: LiveSample, hand: Hand): [number, number] | null {
  const x = hand === "left" ? s[TLX] : s[TRX];
  const y = hand === "left" ? s[TLY] : s[TRY];
  return x == null || y == null ? null : [x, y];
}

/** Where the in-game hand is, for web lobby games that move a hand with the stick; null for the garden. */
export function handCursor(s: LiveSample, hand: Hand): [number, number] | null {
  const i = CLX + (hand === "left" ? 0 : 2);
  const x = s[i] as number | null | undefined,
    y = s[i + 1] as number | null | undefined;
  return x == null || y == null ? null : [x, y];
}

/** The point the game compares with its target: the in-game hand if there is one, else the stick. */
export const handPoint = (s: LiveSample, hand: Hand) => handCursor(s, hand) ?? handPos(s, hand);

export const pct = (v: number | null | undefined, digits = 0) =>
  v == null ? "—" : `${(v * 100).toFixed(digits)}%`;
export const secs = (v: number | null | undefined) =>
  v == null ? "—" : `${v.toFixed(2)} s`;

// The pattern model's outputs, in the neutral wording caregivers see (same as backend/app/insights.py).
// The keys are condition names only because of how the training folders are labelled; no condition
// name is shown. Each score is resemblance to that movement pattern, not a diagnosis.
export const PATTERN_LABELS: Record<PatternKey, string> = {
  parkinson: "Slower, smaller movements in both hands",
  stroke: "One hand weaker or slower than the other",
  essential_tremor: "Rhythmic shake while moving",
};
/** What each pattern looks like in the games, in plain words. */
export const PATTERN_HINTS: Record<PatternKey, string> = {
  parkinson: "Reaches get slower and shorter with both sticks",
  stroke: "One stick lags behind the other on the same task",
  essential_tremor: "A small back-and-forth shake on top of the movement",
};
export const PATTERN_ORDER: PatternKey[] = [
  "parkinson",
  "stroke",
  "essential_tremor",
];
const LEVEL_NAMES: Record<string, string> = {
  apples: "Apples",
  butterfly_left: "Butterfly (left)",
  butterfly_right: "Butterfly (right)",
  water: "Watering",
  lobby: "Lobby",
  apple: "Apple Picking",
  fish: "Harbour Fishing",
  rat: "Rat Catching",
};
export const levelName = (lv: string | null | undefined) =>
  lv ? (LEVEL_NAMES[lv] ?? lv) : "";
