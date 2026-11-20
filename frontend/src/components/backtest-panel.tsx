import { createChart, LineStyle, type Time } from "lightweight-charts"
import React from "react"

import { Frame, SectionTitle } from "@/components/frame"
import { chartTheme } from "@/components/price-chart"
import type { Backtest } from "@/lib/api"
import { cssVar, num, pct, pct0, tone } from "@/lib/format"
import { cn } from "@/lib/utils"

function EquityChart({ bt, scheme }: { bt: Backtest; scheme: string }) {
  const el = React.useRef<HTMLDivElement>(null)
  React.useEffect(() => {
    if (!el.current) return
    const c = createChart(el.current, { autoSize: true, ...chartTheme(), handleScroll: false, handleScale: false })
    const bh = c.addLineSeries({ color: cssVar("--faint"), lineWidth: 1, lineStyle: LineStyle.Solid, priceLineVisible: false, lastValueVisible: false })
    const eq = c.addAreaSeries({
      lineColor: cssVar("--ink"),
      topColor: cssVar("--line-strong"),
      bottomColor: "transparent",
      lineWidth: 2,
      priceLineVisible: false,
    })
    bh.setData(bt.buy_hold.map((p) => ({ time: p.time as Time, value: p.value })))
    eq.setData(bt.equity.map((p) => ({ time: p.time as Time, value: p.value })))
    c.timeScale().fitContent()
    return () => c.remove()
  }, [bt, scheme])
  return <div ref={el} className="h-[220px] w-full" />
}

function Metric({ label, value, sub, className }: { label: string; value: string; sub?: string; className?: string }) {
  return (
    <div className="border border-line bg-paper p-3">
      <div className="font-mono text-[10.5px] tracking-[0.06em] text-faint">{label}</div>
      <div className={cn("tabular mt-1 text-[19px] font-semibold tracking-tight", className)}>{value}</div>
      {sub && <div className="tabular mt-0.5 text-[11.5px] text-muted">{sub}</div>}
    </div>
  )
}

export function BacktestPanel({ bt, error, scheme }: { bt: Backtest | null; error: Error | null; scheme: string }) {
  const m = bt?.metrics
  return (
    <Frame innerClassName="p-4 sm:p-5" id="backtest">
      <SectionTitle
        eyebrow={m ? "backtest · " + m.period : "backtest"}
        title="Geçmişte nasıl performans gösterdi?"
        right={
          <div className="flex items-center gap-4 text-[12px] text-muted">
            <span className="inline-flex items-center gap-1.5">
              <i className="inline-block h-0.5 w-4 bg-ink" />
              Strateji
            </span>
            <span className="inline-flex items-center gap-1.5">
              <i className="inline-block h-0.5 w-4 bg-faint" />
              Al ve tut
            </span>
          </div>
        }
      />
      {error ? (
        <p className="text-sm text-down">Backtest yüklenemedi: {error.message}</p>
      ) : !bt || !m ? (
        <div className="grid h-[330px] place-items-center text-sm text-muted">Hesaplanıyor…</div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
            <Metric label="Getiri" value={pct(m.total_return_pct, 1)} sub={"Al-tut " + pct(m.buy_hold_return_pct, 1)} className={tone(m.total_return_pct)} />
            <Metric label="Max düşüş" value={pct(m.max_drawdown_pct, 1)} sub={"Al-tut " + pct(m.buy_hold_max_drawdown_pct, 1)} className="text-down" />
            <Metric label="Yıllık" value={pct(m.cagr_pct, 1)} sub="Bileşik getiri" className={tone(m.cagr_pct)} />
            <Metric label="İşlem" value={String(m.trades)} sub={"Kazanma " + pct0(m.win_rate_pct)} />
            <Metric label="Profit factor" value={num(m.profit_factor)} sub={"Sharpe " + num(m.sharpe)} />
            <Metric label="Ort. pozisyon" value={pct0(m.avg_position_pct)} sub={"Piyasada " + pct0(m.exposure_pct)} />
          </div>
          <div className="mt-4">
            <EquityChart bt={bt} scheme={scheme} />
          </div>
          <p className="mt-3 text-[12px] text-muted">
            Aynı strateji ve aynı risk ayarıyla geçmiş veride. Komisyon dahil, kayma hariç. Geçmiş performans gelecek için garanti değildir.
          </p>
        </>
      )}
    </Frame>
  )
}
