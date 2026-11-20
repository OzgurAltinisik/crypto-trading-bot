import { Activity, BellRing, CircleOff } from "lucide-react"

import type { Overview } from "@/lib/api"
import { ago } from "@/lib/format"
import { cn } from "@/lib/utils"

export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      <path d="M12 2.5 21.5 12 12 21.5 2.5 12z" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <path d="M12 7.5 16.5 12 12 16.5 7.5 12z" fill="currentColor" />
    </svg>
  )
}

export function Header({ overview, error, updatedAt }: { overview: Overview | null; error: Error | null; updatedAt: Date | null }) {
  const online = overview?.engine.online
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-paper/85 backdrop-blur-md">
      <div className="mx-auto flex max-w-[1180px] items-center justify-between gap-3 px-4 py-3 sm:px-6">
        <a href="#" className="flex items-center gap-2.5 text-ink no-underline">
          <span className="grid size-8 place-items-center bg-inv text-inv-ink">
            <Logo className="size-4.5" />
          </span>
          <span className="leading-tight">
            <span className="block text-[15px] font-semibold tracking-tight">Kripto Sinyal</span>
            <span className="block font-mono text-[10.5px] tracking-[0.06em] text-faint">paper trading · binance</span>
          </span>
        </a>
        <nav className="hidden items-center gap-6 text-[13px] text-muted md:flex">
          <a className="hover:text-ink" href="#botlar">Botlar</a>
          <a className="hover:text-ink" href="#grafik">Grafik</a>
          <a className="hover:text-ink" href="#backtest">Backtest</a>
          <a className="hover:text-ink" href="#islemler">İşlemler</a>
          <a className="hover:text-ink" href="#nasil">Nasıl çalışır</a>
        </nav>
        <div className="flex items-center gap-2 sm:gap-3">
          <a
            href="#bildirim"
            className="inline-flex items-center gap-1.5 bg-inv px-2.5 py-1.5 text-[12.5px] font-semibold text-inv-ink hover:opacity-90"
          >
            <BellRing className="size-3.5" />
            <span className="hidden sm:inline">Bildirim al</span>
          </a>
          <span
            className={cn(
              "inline-flex items-center gap-2 border px-2.5 py-1 text-[12.5px] font-medium",
              error ? "border-down/40 text-down" : online ? "border-line text-soft" : "border-down/40 text-down",
            )}
            title={overview?.engine.heartbeat ? "Motorun son kontrolü: " +new Date(overview.engine.heartbeat).toLocaleString("tr-TR") : undefined}
          >
            {error ? (
              <>
                <CircleOff className="size-3.5" /> Bağlantı yok
              </>
            ) : !overview ? (
              <>Bağlanıyor…</>
            ) : online ? (
              <>
                <span className="relative grid size-2 place-items-center">
                  <span className="pulse-dot absolute size-2 rounded-full bg-up/50" />
                  <span className="size-1.5 rounded-full bg-up" />
                </span>
                Motor çalışıyor
              </>
            ) : (
              <>
                <Activity className="size-3.5" />
                {overview.engine.heartbeat ? "Motor durdu · " + ago(overview.engine.heartbeat) : "Motor kapalı"}
              </>
            )}
          </span>
          {updatedAt && (
            <span className="hidden font-mono text-[11px] text-faint sm:inline">
              {updatedAt.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
            </span>
          )}
        </div>
      </div>
    </header>
  )
}
