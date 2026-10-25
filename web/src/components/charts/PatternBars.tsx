import type { PatternScores, TcnLevel } from "../../api";
import { PATTERN_HINTS, PATTERN_LABELS, PATTERN_ORDER, levelName } from "../../labels";

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
