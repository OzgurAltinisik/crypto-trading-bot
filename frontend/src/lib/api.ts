// Types and fetch helpers for the FastAPI backend (cryptobot/api.py).

export type Position = {
  entry_time: string
  entry_price: number
  stop: number
  initial_stop: number
  take_profit: number | null
  breakeven_active: boolean
  qty: number | null
  unrealized_pct?: number
}

export type Bot = {
  id: string
  symbol: string
  timeframe: string
  strategy: string
  description: string
  risk_per_trade_pct: number | null
  initial_balance: number
  balance: number
  position: Position | null
  last_candle: string | null
  last_exit: string | null
  last_signal: string | null
  price: number | null
  change_24h_pct: number | null
  stats: { trades: number; wins: number; net_usd: number; win_rate_pct: number | null }
}

export type Overview = {
  engine: { heartbeat: string | null; online: boolean }
  bots: Bot[]
  server_time: string
}

export type Point = { time: number; value: number }
export type Candle = { time: number; open: number; high: number; low: number; close: number }
export type Marker = {
  time: number
  kind: "entry" | "exit"
  source: "paper" | "backtest"
  price: number
  pnl_pct?: number
  reason?: string
}
export type ChartData = { candles: Candle[]; lines: Record<string, Point[]>; markers: Marker[]; position: Position | null }

export type Trade = {
  id?: number
  bot_id?: string
  entry_time: string
  entry_price: number
  exit_time: string
  exit_price: number
  pnl_pct: number
  pnl_usd: number
  reason: string
  position_pct: number | null
}

export type Metrics = {
  period: string
  total_return_pct: number
  buy_hold_return_pct: number
  cagr_pct: number | null
  max_drawdown_pct: number
  buy_hold_max_drawdown_pct: number
  sharpe: number | null
  trades: number
  win_rate_pct: number | null
  profit_factor: number | null
  exposure_pct: number | null
  avg_position_pct: number | null
}
export type Backtest = { start: string; metrics: Metrics; equity: Point[]; buy_hold: Point[]; trades: Trade[] }

export type Signal = { id: number; bot_id: string; candle_time: string; side: "BUY" | "SELL"; price: number; acted: number }

export type SiteConfig = {
  email_enabled: boolean
  telegram_bot: string | null
  contact_email: string | null
  bots: { id: string; name: string; symbol: string; strategy: string }[]
}

export type Events = "all" | "entry"
export type Subscription = { channel: "email" | "telegram"; address: string; bots: string[]; events: Events; confirmed: boolean }

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function api<T>(path: string, init?: { method?: string; body?: unknown }): Promise<T> {
  const r = await fetch(path, {
    credentials: "same-origin",
    method: init?.method ?? "GET",
    headers: init?.body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
  })
  if (!r.ok) {
    const body = await r.json().catch(() => ({}))
    const detail = Array.isArray(body.detail) ? "Geçersiz bilgi" : body.detail
    throw new ApiError(r.status, detail ?? r.statusText)
  }
  return r.json() as Promise<T>
}
