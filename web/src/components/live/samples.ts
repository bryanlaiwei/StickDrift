/** Reading one live sample: stick, target and in-game hand positions by hand. */
import { LIVE_SAMPLE_COLUMNS, type LiveSample } from "../../api";

const col = (name: (typeof LIVE_SAMPLE_COLUMNS)[number]) => LIVE_SAMPLE_COLUMNS.indexOf(name);
const LX = col("lx"),
  LY = col("ly"),
  RX = col("rx"),
  RY = col("ry"),
  TLX = col("target_lx"),
  TLY = col("target_ly"),
  TRX = col("target_rx"),
  TRY = col("target_ry"),
  CLX = col("cursor_lx");
/** Samples per second the lobby streams (web/lobby/live.js). */
export const HZ = 60;

export type Hand = "left" | "right";
export const HANDS: Hand[] = ["left", "right"];

export function handPos(s: LiveSample, hand: Hand): [number, number] {
  const [x, y] = hand === "left" ? [s[LX], s[LY]] : [s[RX], s[RY]];
  return [x as number, y as number];
}

export function handTarget(s: LiveSample, hand: Hand): [number, number] | null {
  const x = (hand === "left" ? s[TLX] : s[TRX]) as number | null;
  const y = (hand === "left" ? s[TLY] : s[TRY]) as number | null;
  return x == null || y == null ? null : [x, y];
}

/** Where the in-game hand is, for games that move a hand with the stick; null in Rat Catching. */
export function handCursor(s: LiveSample, hand: Hand): [number, number] | null {
  const i = CLX + (hand === "left" ? 0 : 2);
  const x = s[i] as number | null,
    y = s[i + 1] as number | null;
  return x == null || y == null ? null : [x, y];
}

/** The point the game compares with its target: the in-game hand if there is one, else the stick. */
export const handPoint = (s: LiveSample, hand: Hand) => handCursor(s, hand) ?? handPos(s, hand);
