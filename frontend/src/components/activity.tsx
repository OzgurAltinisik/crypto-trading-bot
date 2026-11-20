import { ArrowDownRight, ArrowUpRight, Inbox } from "lucide-react"

import { Frame, SectionTitle, Tag } from "@/components/frame"
import type { Signal, Trade } from "@/lib/api"
import { money, pct, pct0, REASONS, tone, usd, when } from "@/lib/format"
import { cn } from "@/lib/utils"

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2.5 border border-dashed border-line-strong bg-paper px-3 py-3 text-[13px] text-muted">
      <Inbox className="mt-0.5 size-4 shrink-0" />
      <span>{children}</span>
    </div>
  )
}

/** Live signals; falls back to the latest backtest trades while there are few. */
export function SignalsPanel({ signals, backtestTrades }: { signals: Signal[] | null; backtestTrades: Trade[] }) {
  const few = (signals?.length ?? 0) < 5
  return (
    <Frame innerClassName="flex h-full flex-col p-4 sm:p-5">
      <SectionTitle eyebrow="canlı" title="Son sinyaller" />
      {signals && signals.length > 0 ? (
        <ul className="divide-y divide-line">
          {signals.slice(0, 8).map((s) => (
            <li key={s.id} className="flex items-center justify-between gap-3 py-2.5 text-[13px]">
              <span className="flex items-center gap-2.5">
                {s.side === "BUY" ? <Tag tone="up">AL</Tag> : <Tag tone="down">SAT</Tag>}
                <span className="text-muted">{when(s.candle_time)}</span>
              </span>
              <span className="tabular text-right">
                {money(s.price)}
                <span className="block text-[11px] text-faint">{s.acted ? "işleme girdi" : "uygulanmadı"}</span>
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <Empty>Henüz canlı sinyal yok. Motor her mum kapandığında kontrol eder; 4 saatlik botlarda sinyal genelde birkaç günde bir gelir.</Empty>
      )}
      {few && backtestTrades.length > 0 && (
        <div className="mt-5">
          <div className="mb-1 font-mono text-[10.5px] tracking-[0.06em] text-faint">backtest'teki son işlemler</div>
          <ul className="divide-y divide-line">
            {backtestTrades.slice(0, 6).map((t, i) => (
              <li key={i} className="flex items-center justify-between gap-3 py-2 text-[12.5px]">
                <span className="text-muted">
                  {when(t.entry_time)} <span className="text-faint">→</span> {when(t.exit_time)}
                </span>
                <span className={cn("tabular inline-flex items-center gap-1 font-semibold", tone(t.pnl_pct))}>
                  {t.pnl_pct > 0 ? <ArrowUpRight className="size-3.5" /> : <ArrowDownRight className="size-3.5" />}
                  {pct(t.pnl_pct, 1)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Frame>
  )
}

export function TradesTable({
  trades,
  backtestTrades,
  botId,
  tab,
  setTab,
  onlySelected,
  setOnlySelected,
}: {
  trades: Trade[] | null
  backtestTrades: Trade[] | null
  botId: string
  tab: "live" | "backtest"
  setTab: (t: "live" | "backtest") => void
  onlySelected: boolean
  setOnlySelected: (v: boolean) => void
}) {
  const rows = tab === "live" ? trades : backtestTrades
  const tabs: ["live" | "backtest", string, number | undefined][] = [
    ["live", "Canlı", trades?.length],
    ["backtest", "Backtest", backtestTrades?.length],
  ]
  return (
    <Frame innerClassName="p-4 sm:p-5" id="islemler">
      <SectionTitle
        eyebrow={tab === "live" ? "paper trading · tüm botlar" : "backtest · " + botId + " · son 50 işlem"}
        title="İşlem geçmişi"
        right={
          <div className="flex flex-wrap items-center gap-4">
            {tab === "live" && (
              <label className="inline-flex cursor-pointer items-center gap-2 text-[12.5px] text-muted select-none">
                <input type="checkbox" className="size-3.5 accent-[var(--ink)]" checked={onlySelected} onChange={(e) => setOnlySelected(e.target.checked)} />
                Sadece seçili bot
              </label>
            )}
            <div className="inline-flex border border-line bg-paper p-0.5" role="tablist" aria-label="İşlem kaynağı">
              {tabs.map(([key, label, n]) => (
                <button
                  key={key}
                  type="button"
                  role="tab"
                  aria-selected={tab === key}
                  onClick={() => setTab(key)}
                  className={cn("px-3 py-1 text-[12.5px] transition-colors", tab === key ? "bg-inv text-inv-ink" : "text-muted hover:text-ink")}
                >
                  {label}
                  {n != null && <span className="ml-1.5 font-mono text-[10.5px] opacity-70">{n}</span>}
                </button>
              ))}
            </div>
          </div>
        }
      />
      {rows && rows.length === 0 ? (
        <Empty>
          {tab === "live"
            ? "Henüz kapanmış canlı işlem yok. Botun geçmişte nasıl işlem yaptığını görmek için Backtest sekmesine bak."
            : "Bu bot için backtest işlemi yok."}
        </Empty>
      ) : !rows ? (
        <div className="grid h-32 place-items-center text-sm text-muted">Yükleniyor…</div>
      ) : (
        <div className="-mx-4 overflow-x-auto sm:mx-0">
          <table className="w-full min-w-[640px] border-collapse text-[13px]">
            <thead>
              <tr className="border-b border-line text-left font-mono text-[10.5px] tracking-[0.06em] text-faint">
                <th className="px-4 py-2 font-normal sm:px-2">Bot</th>
                <th className="px-2 py-2 font-normal">Giriş</th>
                <th className="px-2 py-2 font-normal">Çıkış</th>
                <th className="px-2 py-2 text-right font-normal">Giriş $</th>
                <th className="px-2 py-2 text-right font-normal">Çıkış $</th>
                <th className="px-2 py-2 text-right font-normal">Boyut</th>
                <th className="px-2 py-2 text-right font-normal">K/Z</th>
                <th className="px-4 py-2 font-normal sm:px-2">Sebep</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t, i) => (
                <tr key={t.id ?? i} className="border-b border-line last:border-0">
                  <td className="px-4 py-2.5 font-medium sm:px-2">
                    {t.bot_id ?? botId}
                    {tab === "backtest" && <span className="ml-2 font-mono text-[10.5px] font-normal text-faint">bt</span>}
                  </td>
                  <td className="px-2 py-2.5 text-muted">{when(t.entry_time)}</td>
                  <td className="px-2 py-2.5 text-muted">{when(t.exit_time)}</td>
                  <td className="tabular px-2 py-2.5 text-right">{money(t.entry_price)}</td>
                  <td className="tabular px-2 py-2.5 text-right">{money(t.exit_price)}</td>
                  <td className="tabular px-2 py-2.5 text-right text-muted">{pct0(t.position_pct)}</td>
                  <td className={cn("tabular px-2 py-2.5 text-right font-semibold", tone(t.pnl_pct))}>
                    {pct(t.pnl_pct)}
                    <span className="block text-[11px] font-normal">{usd(t.pnl_usd)}</span>
                  </td>
                  <td className="px-4 py-2.5 text-muted sm:px-2">{REASONS[t.reason] ?? t.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Frame>
  )
}
