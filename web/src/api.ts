// All requests go through the Vite proxy (/api -> FastAPI) so the HttpOnly
// session cookie is same-origin.
const API = '/api'

export type Hand = 'left' | 'right' | 'unknown'
export type Role = 'senior' | 'caregiver'

export interface Me {
  role: Role
  account_id: string
  username: string
  display_name: string
  dominant_hand: Hand | null
}

export interface Review {
  flagged: boolean
  reasons: string[]
}

export type Risk = 'none' | 'watch' | 'check'
/** One measurement of one game and hand compared with the resident's usual, e.g. apple_reach_s_left. */
export interface Finding {
  key: string
  label: string
  hand: 'left' | 'right'
  /** seconds and distance: higher is worse; share (time on the lane): lower is worse */
  kind: 'seconds' | 'distance' | 'share'
  baseline: number
  latest: number
  change: number
  baseline_text: string
  latest_text: string
  change_text: string
  direction: 'worse' | 'better' | 'steady'
  flagged: boolean
  persistent: boolean
  flagged_visit_ids: string[]
  text: string
}

export interface Concern {
  id: string
  title: string
  level: 'watch' | 'check'
  summary: string
  evidence: string[]
  possible_contributors: string[]
  recommended_checks: string[]
  references: string[]
  measurements: string[]
}

export interface Insights {
  status: 'ok' | 'insufficient'
  risk: Risk
  summary: string
  disclaimer: string
  usable_visits: number
  game_visits?: number
  baseline_visits: number
  recent_visit_ids: string[]
  findings: Finding[]
  concerns: Concern[]
}

export interface ResidentRow {
  participant_id: string
  username: string | null
  display_name: string
  dominant_hand: Hand
  session_count: number
  last_played_at: string | null
  review: Review
  risk: Risk
  concerns: Pick<Concern, 'id' | 'title' | 'level'>[]
}

export type PatternKey = 'parkinson' | 'stroke' | 'essential_tremor'
/** Older sessions may omit a pattern the current model no longer returns. */
export type PatternScores = Partial<Record<PatternKey, number | null>>

export interface TcnLevel {
  level: string
  completed: boolean
  scores: PatternScores
  stretches?: { left: number; right: number }
  duration_s?: number
  error?: string
}

export interface TcnResult {
  scores: PatternScores
  levels: TcnLevel[]
  meaning: string
  is_synthetic: boolean
}

export interface HandLive {
  reaction_s: number | null
  reach_s: number | null
  peak_speed: number | null
  reach_size: number | null
  apples_reached: number | null
  apples_total: number | null
  speed_change_pct: number | null
  tracking_error: number | null
  on_target: number | null
  shake: number | null
  shake_hz: number | null
}

export interface ReachTrial {
  trial: number
  /** the lobby game the attempt came from */
  game?: string
  left?: { reaction_s: number | null; reach_s: number | null; peak_speed: number; reach_size: number | null; reached: boolean }
  right?: { reaction_s: number | null; reach_s: number | null; peak_speed: number; reach_size: number | null; reached: boolean }
}

export interface LiveMetrics {
  hands: { left: HandLive; right: HandLive }
  left_right_difference_pct: Partial<Record<keyof HandLive, number>>
  reach_trials: ReachTrial[]
  tracking: Record<string, Record<string, { tracking_error: number; on_target: number; shake: number | null }>>
}

export interface ResidentDetail {
  participant_id: string
  username: string | null
  display_name: string
  dominant_hand: Hand
  review: Review
  insights: Insights
  game_sessions: GameSession[]
}

export type LobbyGame = 'apple' | 'fish' | 'rat'

/** One web lobby game within a visit. Apples picked and rats caught use apples_reached / apples_total. */
export interface GameResult {
  hands: { left: HandLive; right: HandLive }
  left_right_difference_pct: Partial<Record<keyof HandLive, number>>
  attempts: number
  samples: number
  play_s: number
  finished: boolean
}

export interface GameSession {
  session_id: string
  started_at: string
  completed_at: string | null
  status: string
  is_synthetic: boolean
  games: Partial<Record<LobbyGame, GameResult>>
  games_finished: LobbyGame[]
  /** Pattern-model scores for Apple Picking + Harbour Fishing; null until scored or without a trained model. */
  tcn?: (TcnResult & { by_game?: Partial<Record<LobbyGame, { scores: PatternScores }>> }) | null
  /** The full visit report (ml/visit_report/report.py), including Rat Catching timing. */
  visit?: { games?: { rat?: RatReport | null } } | null
  /** A reconstructed-hands GIF was stored for this visit (handReplayUrl). Older visits have none. */
  has_hand_replay?: boolean
  hand_replay?: HandReplayInfo | null
}

/** Which stretch of the visit the reconstructed-hands GIF shows. */
export interface HandReplayInfo {
  game: LobbyGame
  window_start_s: number | null
  duration_s: number | null
  /** False when the controller sent no gyroscope values, so the GIF has no shake. */
  has_motion: boolean | null
}

export interface RatReport {
  score: number | null
  stars: number | null
  caught?: number | null
  missed?: number | null
  wrong?: number | null
  empty?: number | null
  target_rats: number | null
  correctness_pct: number | null
  median_reaction_s: number | null
  reaction_spread_s?: number | null
  early_slams?: number
}

export type LiveStatus = 'ready' | 'playing' | 'scoring' | 'finished' | 'failed' | 'lost' | 'ended'

export interface LiveBrief {
  live_id: string
  participant_id: string
  name: string
  status: LiveStatus
  level: string | null
  levels: string[]
  levels_done: string[]
  synthetic: boolean
  started_at: string
  elapsed_s: number
  tcn_scores: PatternScores | null
  /** Rat Catching points from the visit that just ended. Null while playing, or when that game was not played. */
  rat: RatReport | null
  db_session_id: string | null
  error: string | null
}

/**
 * The columns of one live sample: seq and level from the API, then the lobby's sample in the order
 * web/lobby/measure.js produces it (SAMPLE_KEYS in backend/app/measurements.py).
 */
export const LIVE_SAMPLE_COLUMNS = [
  'seq', 'level', 't', 'trial', 'phase',
  'lx', 'ly', 'rx', 'ry',
  'target_lx', 'target_ly', 'target_rx', 'target_ry',
  'on_l', 'on_r',
  'cursor_lx', 'cursor_ly', 'cursor_rx', 'cursor_ry',
] as const

/** One live sample, in LIVE_SAMPLE_COLUMNS order. Targets and the in-game hand are null when a game has none. */
export type LiveSample = [
  number, string, number, number | null, string,
  number, number, number, number,
  number | null, number | null, number | null, number | null,
  number, number,
  number | null, number | null, number | null, number | null,
]

export interface LiveSnapshot extends LiveBrief {
  trial: number | null
  phase: string | null
  seq: number
  samples: LiveSample[]
  metrics: LiveMetrics
  /** Pattern scores per game and the rat-game score, once the visit is scored. */
  result: (Partial<TcnResult> & { scores?: PatternScores | null; rat?: RatReport | null }) | null
  /** The visit's reconstructed-hands GIF is stored (lobby visits only). */
  hand_replay_ready?: boolean
  hand_replay?: HandReplayInfo | null
  /** The GIF is still being drawn after the visit ended. */
  hand_replay_pending?: boolean
}

export interface ChatTurn {
  role: 'user' | 'assistant'
  text: string
}

export interface AssistantAnswer {
  answer: string
  source: 'gemini' | 'rules'
  grounded: boolean
  unverified_numbers: string[]
  note: string | null
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
  } catch {
    throw new ApiError(0, "Can't reach the Stick Drift server. Is the backend running?")
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    const detail =
      typeof body?.detail === 'string'
        ? body.detail
        : res.status >= 500
          ? 'The server had a problem. Try again in a moment.'
          : 'Please check what you entered and try again.'
    throw new ApiError(res.status, detail)
  }
  return (res.status === 204 ? undefined : await res.json()) as T
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

async function download(path: string): Promise<{ blob: Blob; filename: string; source: string }> {
  let res: Response
  try {
    res = await fetch(`${API}${path}`)
  } catch {
    throw new ApiError(0, "Can't reach the Stick Drift server. Is the backend running?")
  }
  if (!res.ok) throw new ApiError(res.status, 'The report could not be created. Try again in a moment.')
  const match = /filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') ?? '')
  return { blob: await res.blob(), filename: match?.[1] ?? 'stick-drift-summary.pdf', source: res.headers.get('X-Report-Source') ?? '' }
}

/** Same origin as the page, so a plain <img src> carries the caregiver's login cookie. */
export const handReplayUrl = (sessionId: string) => `${API}/caregiver/sessions/${sessionId}/hand-replay.gif`

export const api = {
  me: () => request<Me>('/auth/me'),
  loginSenior: (username: string, password: string) =>
    post<Me>('/auth/senior/login', { username, password }),
  signupSenior: (username: string, password: string, dominant_hand: Hand) =>
    post<Me>('/auth/senior/signup', { username, password, dominant_hand }),
  signupCaregiver: (username: string, password: string, display_name: string, invite_code: string) =>
    post<Me>('/auth/caregiver/signup', { username, password, display_name, invite_code }),
  loginCaregiver: (username: string, password: string) =>
    post<Me>('/auth/caregiver/login', { username, password }),
  logout: () => post<void>('/auth/logout'),


  caregiverResidents: () => request<ResidentRow[]>('/caregiver/residents'),
  caregiverResident: (id: string) => request<ResidentDetail>(`/caregiver/residents/${id}`),
  // the PDF prints times in the reader's zone so they match the site
  residentReport: (id: string) =>
    download(
      `/caregiver/residents/${id}/report.pdf?tz=${encodeURIComponent(Intl.DateTimeFormat().resolvedOptions().timeZone)}`,
    ),
  caregiverLive: () => request<LiveBrief[]>('/caregiver/live'),
  caregiverLiveSnapshot: (id: string, since: number) =>
    request<LiveSnapshot>(`/caregiver/live/${id}?since=${since}`),
  askAssistant: (question: string, history: ChatTurn[], participantId?: string) =>
    post<AssistantAnswer>('/caregiver/assistant', { question, history, participant_id: participantId ?? null }),
}
