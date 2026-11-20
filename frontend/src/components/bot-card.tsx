import { ArrowDownRight, ArrowUpRight } from "lucide-react"

import { Frame, Tag } from "@/components/frame"
import type { Bot } from "@/lib/api"
import { ago, money, pct, pct0, STRATEGY_NAMES, tone, usd0 } from "@/lib/format"
import { cn } from "@/lib/utils"

export function BotCard({ bot, active, onSelect }: { bot: Bot; active: boolean; onSelect: () => void }) {
  const p = bot.position
  const ret = (bot.balance / bot.initial_balance - 1) * 100
  const [base, quote] = bot.symbol.split("/")
  const up = (bot.change_24h_pct ?? 0) >= 0
  // last time the bot actually traded: the open position's entry or the last exit
  const last = [p?.entry_time, bot.last_exit].filter(Boolean).sort().pop() ?? null
  return (
    <Frame
      as="button"
      hover
      active={active}
      onClick={onSelect}
      aria-pressed={active}
      className="block w-full cursor-pointer text-left"
      innerClassName="flex flex-col gap-3 p-4"
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-[15px] font-semibold tracking-tight">
            {base}
            <span className="text-faint">/{quote}</span>
            <span className="ml-1.5 font-mono text-[11px] font-normal text-muted">{bot.timeframe}</span>
          </div>
          <div className="mt-0.5 text-[12px] text-muted">{STRATEGY_NAMES[bot.strategy] ?? bot.strategy}</div>
        </div>
        {p ? <Tag tone="up">Pozisyonda</Tag> : <Tag>Beklemede</Tag>}
      </div>

      <div className="flex items-baseline justify-between gap-2">
        <span className="tabular text-[22px] font-semibold tracking-tight">{money(bot.price)}</span>
        <span className={cn("tabular inline-flex items-center gap-0.5 text-[12.5px] font-medium", tone(bot.change_24h_pct))}>
          {up ? <ArrowUpRight className="size-3.5" /> : <ArrowDownRight className="size-3.5" />}
          {pct(bot.change_24h_pct)}
        </span>
      </div>

      <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 border-t border-line pt-3 text-[12px]">
        {p ? (
          <>
            <dt className="text-muted">Açık K/Z</dt>
            <dd className={cn("tabular text-right font-semibold", tone(p.unrealized_pct))}>{pct(p.unrealized_pct)}</dd>
          </>
        ) : null}
        <dt className="text-muted">Sanal bakiye</dt>
        <dd className="tabular text-right font-semibold">
          {usd0(bot.balance)} <span className={cn("font-medium", tone(ret))}>{pct(ret, 1)}</span>
        </dd>
        <dt className="text-muted">İşlem · kazanma</dt>
        <dd className="tabular text-right font-semibold">
          {bot.stats.trades} · {bot.stats.win_rate_pct == null ? "—" : pct0(bot.stats.win_rate_pct)}
        </dd>
        <dt className="text-muted">Son işlem</dt>
        <dd className="tabular text-right font-semibold" title={last ? new Date(last).toLocaleString("tr-TR") : undefined}>
          {last ? ago(last) : <span className="font-normal text-faint">henüz yok</span>}
        </dd>
        <dt className="text-muted">Risk / işlem</dt>
        <dd className="tabular text-right font-semibold">{bot.risk_per_trade_pct == null ? "Tüm bakiye" : "%" + bot.risk_per_trade_pct.toLocaleString("tr-TR")}</dd>
      </dl>
    </Frame>
  )
}
