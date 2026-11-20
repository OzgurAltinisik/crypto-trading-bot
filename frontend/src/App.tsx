import { BellRing, LockKeyhole } from "lucide-react"
import React from "react"

import { SignalsPanel, TradesTable } from "@/components/activity"
import { BacktestPanel } from "@/components/backtest-panel"
import { BotCard } from "@/components/bot-card"
import { Frame, SectionTitle, Tag } from "@/components/frame"
import { Header, Logo } from "@/components/header"
import { HowItWorks } from "@/components/how-it-works"
import { PriceChart } from "@/components/price-chart"
import { SubscribeSection } from "@/components/subscribe"
import { usePoll, useScheme } from "@/hooks/use-data"
import { ApiError, type Backtest, type Bot, type ChartData, type Overview, type Signal, type SiteConfig, type Trade } from "@/lib/api"
import { money, pct, pct0, tone, usd0, when } from "@/lib/format"
import { cn } from "@/lib/utils"

function Kpi({ label, value, sub, className }: { label: string; value: React.ReactNode; sub?: React.ReactNode; className?: string }) {
  return (
    <div className="border-line px-4 py-3 sm:px-5 [&:not(:first-child)]:border-l">
      <div className="font-mono text-[10.5px] tracking-[0.06em] text-faint">{label}</div>
      <div className={cn("tabular mt-1 text-xl font-semibold tracking-tight sm:text-2xl", className)}>{value}</div>
      {sub && <div className="mt-0.5 text-[12px] text-muted">{sub}</div>}
    </div>
  )
}

function Hero({ overview }: { overview: Overview | null }) {
  const bots = overview?.bots ?? []
  const open = bots.filter((b) => b.position).length
  const balance = bots.reduce((s, b) => s + b.balance, 0)
  const initial = bots.reduce((s, b) => s + b.initial_balance, 0)
  const trades = bots.reduce((s, b) => s + b.stats.trades, 0)
  const ret = initial ? (balance / initial - 1) * 100 : null
  return (
    <section className="pt-10 pb-8 sm:pt-14">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Tag>Paper trading · gerçek emir yok</Tag>
        <Tag>Binance spot · 4 saatlik mumlar</Tag>
      </div>
      <h1 className="max-w-3xl text-[34px] leading-[1.06] font-medium tracking-[-0.03em] sm:text-[48px]">
        Trendi takip eden botlar,
        <span className="block text-faint">şeffaf sonuçlarla.</span>
      </h1>
      <p className="mt-4 max-w-2xl text-[15px] leading-relaxed text-muted">
        Donchian kanal kırılımı stratejisi BTC, ETH ve SOL'de 7/24 çalışır. Her işlemde bakiyenin küçük bir kısmı riske edilir. Sinyaller, pozisyonlar ve
        backtest sonuçları bu panelde herkese açık.
      </p>
      <div className="mt-6 flex flex-wrap gap-3">
        <a href="#bildirim" className="inline-flex items-center gap-2 bg-inv px-4 py-2.5 text-[14px] font-semibold text-inv-ink hover:opacity-90">
          <BellRing className="size-4" /> Bildirim al
        </a>
        <a href="#botlar" className="inline-flex items-center gap-2 border border-line-strong px-4 py-2.5 text-[14px] hover:border-ink">
          Botları incele
        </a>
      </div>
      <Frame className="mt-8" innerClassName="grid grid-cols-2 lg:grid-cols-4 [&>*:nth-child(3)]:border-l-0 lg:[&>*:nth-child(3)]:border-l [&>*:nth-child(n+3)]:border-t lg:[&>*:nth-child(n+3)]:border-t-0">
        <Kpi label="Aktif bot" value={overview ? bots.length : "—"} sub={[...new Set(bots.map((b) => b.symbol.split("/")[0]))].join(" · ") || " "} />
        <Kpi label="Açık pozisyon" value={overview ? open : "—"} sub={open ? "piyasada" : "hepsi nakitte bekliyor"} />
        <Kpi label="Toplam sanal bakiye" value={overview ? usd0(balance) : "—"} sub={<span className={tone(ret)}>{pct(ret, 2)} başlangıçtan</span>} />
        <Kpi label="Kapanan işlem" value={overview ? trades : "—"} sub="canlı paper trading" />
      </Frame>
    </section>
  )
}

function PositionBar({ bot }: { bot: Bot }) {
  const p = bot.position
  if (!p) return null
  const size = p.qty != null ? (p.qty * p.entry_price) / bot.balance * 100 : 100
  const items: [string, React.ReactNode][] = [
    ["Giriş", money(p.entry_price)],
    ["Stop", money(p.stop)],
    ...(p.take_profit ? ([["Hedef", money(p.take_profit)]] as [string, React.ReactNode][]) : []),
    ["Büyüklük", pct0(size)],
    ["Açık K/Z", <span className={tone(p.unrealized_pct)}>{pct(p.unrealized_pct)}</span>],
  ]
  return (
    <div className="mb-4 flex flex-wrap items-center gap-x-6 gap-y-2 border border-line bg-up-bg px-3 py-2.5 text-[13px]">
      <Tag tone="up">Açık pozisyon · {when(p.entry_time)}</Tag>
      {items.map(([k, v]) => (
        <span key={k} className="text-muted">
          {k} <b className="tabular font-semibold text-ink">{v}</b>
        </span>
      ))}
    </div>
  )
}

const RANGES: [number, string][] = [
  [90, "3A"],
  [180, "6A"],
  [365, "1Y"],
  [730, "2Y"],
]

function ChartSection({
  bot,
  chart,
  error,
  scheme,
  days,
  setDays,
}: {
  bot: Bot
  chart: ChartData | null
  error: Error | null
  scheme: string
  days: number
  setDays: (d: number) => void
}) {
  const legend = Object.keys(chart?.lines ?? {})
  return (
    <Frame innerClassName="p-4 sm:p-5" id="grafik">
      <SectionTitle
        eyebrow={bot.id}
        title={`${bot.symbol} · ${bot.timeframe}`}
        right={
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-muted">
            {legend.map((n) => (
              <span key={n} className="inline-flex items-center gap-1.5">
                <i className={cn("inline-block w-4 border-t", n.startsWith("Kanal") ? "border-dashed" : "border-solid border-t-2", n === "Kanal alt" || n === "EMA yavaş" ? "border-muted" : n === "EMA trend" ? "border-faint" : "border-ink")} />
                {n}
              </span>
            ))}
            <span className="inline-flex items-center gap-1">
              <span className="text-up">▲</span>
              <span className="text-down">▼</span> Canlı işlem
            </span>
            <span className="inline-flex items-center gap-1 text-faint">▲▼ <span className="text-muted">Backtest</span></span>
          </div>
        }
      />
      <div className="-mt-2 mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-[12.5px] text-muted">{bot.description}</p>
        <div className="inline-flex border border-line bg-paper p-0.5" role="group" aria-label="Zaman aralığı">
          {RANGES.map(([d, label]) => (
            <button
              key={d}
              type="button"
              onClick={() => setDays(d)}
              aria-pressed={days === d}
              className={cn(
                "px-2.5 py-1 font-mono text-[11.5px] transition-colors",
                days === d ? "bg-inv text-inv-ink" : "text-muted hover:text-ink",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <PositionBar bot={bot} />
      {error ? (
        <div className="grid h-[340px] place-items-center text-sm text-down sm:h-[440px]">Grafik yüklenemedi: {error.message}</div>
      ) : (
        <div className="relative">
          {!chart && <div className="absolute inset-0 z-10 grid place-items-center text-sm text-muted">Yükleniyor…</div>}
          <PriceChart data={chart} scheme={scheme} fitKey={bot.id + ":" + days} />
        </div>
      )}
      <p className="mt-3 text-[12px] text-faint">Grafik yalnızca kapanmış mumları gösterir; sinyaller de mum kapanınca üretilir.</p>
    </Frame>
  )
}

function Locked() {
  return (
    <div className="grid min-h-screen place-items-center px-4">
      <Frame innerClassName="max-w-sm p-8 text-center">
        <LockKeyhole className="mx-auto mb-4 size-6" />
        <h1 className="text-xl font-semibold tracking-tight">Davet linki gerekli</h1>
        <p className="mt-2 text-sm text-muted">Bu panel sadece davet linkiyle açılır. Linki paylaşan kişiden yeni bir link iste.</p>
      </Frame>
    </div>
  )
}

export default function App() {
  const scheme = useScheme()
  const overview = usePoll<Overview>("/api/overview", 30_000)
  const siteConfig = usePoll<SiteConfig>("/api/config", 0)
  const [selected, setSelected] = React.useState<string | null>(() => new URLSearchParams(location.search).get("bot"))
  const [days, setDays] = React.useState(365)
  const [tradeTab, setTradeTab] = React.useState<"live" | "backtest" | null>(null)
  const [onlySelected, setOnlySelected] = React.useState(false)
  const [updatedAt, setUpdatedAt] = React.useState<Date | null>(null)

  const bots = overview.data?.bots ?? []
  const bot = bots.find((b) => b.id === selected) ?? bots.find((b) => b.position) ?? bots[0] ?? null

  React.useEffect(() => {
    if (overview.data) setUpdatedAt(new Date())
  }, [overview.data])
  React.useEffect(() => {
    const on = () => setSelected(new URLSearchParams(location.search).get("bot"))
    window.addEventListener("popstate", on)
    return () => window.removeEventListener("popstate", on)
  }, [])

  const id = bot ? encodeURIComponent(bot.id) : null
  const chart = usePoll<ChartData>(id && `/api/bots/${id}/chart?days=${days}`, 60_000)
  const bt = usePoll<Backtest>(id && `/api/bots/${id}/backtest`, 0)
  const signals = usePoll<Signal[]>(id && `/api/signals?bot_id=${id}&limit=20`, 60_000)
  const trades = usePoll<Trade[]>(onlySelected && id ? `/api/trades?bot_id=${id}&limit=100` : "/api/trades?limit=100", 60_000)

  const select = (botId: string) => {
    setSelected(botId)
    const url = new URL(location.href)
    url.searchParams.set("bot", botId)
    history.replaceState(null, "", url.pathname + url.search + url.hash)
  }

  if (overview.error instanceof ApiError && overview.error.status === 401) return <Locked />

  return (
    <>
      <Header overview={overview.data} error={overview.error} updatedAt={updatedAt} />
      <main className="mx-auto max-w-[1180px] px-4 pb-10 sm:px-6">
        <Hero overview={overview.data} />

        <section id="botlar">
          <SectionTitle eyebrow="botlar" title="Hangi botu incelemek istersin?" />
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {overview.data
              ? bots.map((b) => <BotCard key={b.id} bot={b} active={b.id === bot?.id} onSelect={() => select(b.id)} />)
              : Array.from({ length: 4 }, (_, i) => <Frame key={i} innerClassName="h-[214px] animate-pulse" children={null} />)}
          </div>
        </section>

        {bot && (
          <div className="mt-8 grid gap-6">
            <div className="scroll-mt-20">
              <ChartSection bot={bot} chart={chart.data} error={chart.error} scheme={scheme} days={days} setDays={setDays} />
            </div>
            <div className="grid gap-6 lg:grid-cols-[1.55fr_1fr]">
              <div className="scroll-mt-20">
                <BacktestPanel bt={bt.data} error={bt.error} scheme={scheme} />
              </div>
              <SignalsPanel signals={signals.data} backtestTrades={bt.data?.trades ?? []} />
            </div>
            <div className="scroll-mt-20">
              <TradesTable
                trades={trades.data}
                backtestTrades={bt.data?.trades ?? null}
                botId={bot.id}
                tab={tradeTab ?? ((trades.data?.length ?? 0) > 0 ? "live" : "backtest")}
                setTab={setTradeTab}
                onlySelected={onlySelected}
                setOnlySelected={setOnlySelected}
              />
            </div>
          </div>
        )}

        <div className="mt-12">
          <SubscribeSection config={siteConfig.data} defaultBot={bot?.id ?? null} />
        </div>
      </main>

      <HowItWorks bt={bt.data} botLabel={bot ? bot.symbol.split("/")[0] + " Donchian" : "BTC"} />

      <footer className="border-t border-line bg-paper">
        <div className="mx-auto flex max-w-[1180px] flex-col gap-3 px-4 py-6 text-[12.5px] text-muted sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <span className="flex items-center gap-2 text-ink">
            <Logo className="size-4" /> <span className="font-semibold">Kripto Sinyal</span>
          </span>
          <span>
            Tüm işlemler sanal bakiyeyle yapılır, gerçek emir gönderilmez. Yatırım tavsiyesi değildir. ·{" "}
            <a href="/gizlilik" className="underline underline-offset-2 hover:text-ink">
              Aydınlatma metni
            </a>
          </span>
        </div>
      </footer>
    </>
  )
}
