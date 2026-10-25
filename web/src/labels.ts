import type { PatternKey, PatternScores } from "./api";

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
  lobby: "Lobby",
  apple: "Apple Picking",
  fish: "Harbour Fishing",
  rat: "Rat Catching",
};
export const levelName = (lv: string | null | undefined) =>
  lv ? (LEVEL_NAMES[lv] ?? lv) : "";

export function hasPatternScores(scores: PatternScores | null | undefined) {
  return !!scores && PATTERN_ORDER.some((k) => scores[k] != null);
}
