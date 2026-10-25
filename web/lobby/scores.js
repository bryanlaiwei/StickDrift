// Per-game high scores and stars, kept in localStorage.
//
// The lobby is single-player for now, so everything is stored under one placeholder player id. The data is already
// keyed by player (players[playerId][game]) so wiring in the dashboard's users later is just a matter of
// calling setPlayer(userId) after login - nothing else here needs to change.
const KEY = 'stickdrift.lobby.scores.v1'
export const MAX_STARS = 3

let playerId = 'player-1'
export const setPlayer = (id) => (playerId = id)
export const getPlayer = () => playerId

function load() {
  try {
    return JSON.parse(localStorage.getItem(KEY)) || { players: {} }
  } catch {
    return { players: {} }
  }
}
function save(db) {
  try {
    localStorage.setItem(KEY, JSON.stringify(db))
  } catch {
    /* private mode / storage full: scores just won't persist */
  }
}

/** { best, stars, plays, last } for a game (zeros if never played). `stars` is the best star count ever earned. */
export function bestFor(game, player = playerId) {
  const g = load().players[player]?.[game]
  return g || { best: 0, stars: 0, plays: 0, last: 0 }
}

/** Store a finished run. Returns { isNewBest, prevBest, best, stars, plays }. */
export function record(game, { score, stars }, player = playerId) {
  const db = load()
  const mine = (db.players[player] ||= {})
  const prev = mine[game] || { best: 0, stars: 0, plays: 0, last: 0 }
  const isNewBest = score > prev.best
  mine[game] = {
    best: Math.max(prev.best, score),
    stars: Math.max(prev.stars, stars),
    plays: prev.plays + 1,
    last: score,
  }
  save(db)
  return { isNewBest, prevBest: prev.best, best: mine[game].best, stars: mine[game].stars, plays: mine[game].plays }
}
