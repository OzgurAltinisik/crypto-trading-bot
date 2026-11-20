const nf = (d: number) => new Intl.NumberFormat("tr-TR", { minimumFractionDigits: d, maximumFractionDigits: d })
const f0 = nf(0)
const f1 = nf(1)
const f2 = nf(2)
const f4 = nf(4)

export const num = (v: number | null | undefined, d = 2) => (v == null ? "—" : nf(d).format(v))
export const money = (v: number | null | undefined) => (v == null ? "—" : "$" + (Math.abs(v) >= 100 ? f2 : f4).format(v))
export const usd = (v: number | null | undefined) => (v == null ? "—" : (v < 0 ? "−$" : "$") + f2.format(Math.abs(v)))
export const usd0 = (v: number | null | undefined) => (v == null ? "—" : (v < 0 ? "−$" : "$") + f0.format(Math.abs(v)))
export const pct = (v: number | null | undefined, d = 2) =>
  v == null ? "—" : (v > 0 ? "+" : v < 0 ? "−" : "") + nf(d).format(Math.abs(v)) + "%"
export const pct0 = (v: number | null | undefined) => (v == null ? "—" : f0.format(v) + "%")
export const pct1 = (v: number | null | undefined) => (v == null ? "—" : f1.format(v) + "%")
export const tone = (v: number | null | undefined) => (v == null || v === 0 ? "text-soft" : v > 0 ? "text-up" : "text-down")

/** "04 Kas 15:00", with the year added when it is not the current year. */
export function when(iso: string | null | undefined) {
  if (!iso) return "—"
  const d = new Date(iso)
  const year = d.getFullYear() !== new Date().getFullYear() ? { year: "numeric" as const } : {}
  return d.toLocaleString("tr-TR", { day: "2-digit", month: "short", ...year, hour: "2-digit", minute: "2-digit" })
}

export function ago(iso: string | null | undefined) {
  if (!iso) return ""
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return "az önce"
  if (s < 3600) return Math.round(s / 60) + " dk önce"
  if (s < 86400) return Math.round(s / 3600) + " sa önce"
  return Math.round(s / 86400) + " gün önce"
}

export const REASONS: Record<string, string> = {
  "STOP-LOSS": "Stop-loss",
  "TAKE-PROFIT": "Hedef",
  "SELL SIGNAL": "Satış sinyali",
  "BREAKEVEN STOP": "Başabaş stop",
  "TRAILING STOP": "İz süren stop",
}

export const STRATEGY_NAMES: Record<string, string> = { donchian: "Donchian kırılımı", ema_cross: "EMA kesişimi" }

export function cssVar(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}
