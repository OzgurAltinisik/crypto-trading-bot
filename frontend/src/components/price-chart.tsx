import {
  ColorType,
  createChart,
  CrosshairMode,
  LineStyle,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type SeriesMarker,
  type Time,
} from "lightweight-charts"
import React from "react"

import type { ChartData } from "@/lib/api"
import { cssVar, pct } from "@/lib/format"

const LINE_STYLE: Record<string, { color: string; dashed: boolean; width: 1 | 2 }> = {
  "Kanal üst": { color: "--ink", dashed: true, width: 1 },
  "Kanal alt": { color: "--muted", dashed: true, width: 1 },
  "EMA trend": { color: "--faint", dashed: false, width: 2 },
  "EMA hızlı": { color: "--ink", dashed: false, width: 1 },
  "EMA yavaş": { color: "--muted", dashed: false, width: 1 },
}

export function chartTheme() {
  return {
    layout: {
      background: { type: ColorType.Solid, color: "transparent" },
      textColor: cssVar("--muted"),
      fontFamily: "JetBrains Mono, ui-monospace, monospace",
      fontSize: 11,
    },
    grid: { vertLines: { color: cssVar("--line") }, horzLines: { color: cssVar("--line") } },
    rightPriceScale: { borderColor: cssVar("--line") },
    timeScale: { borderColor: cssVar("--line"), timeVisible: true, secondsVisible: false },
    crosshair: {
      mode: CrosshairMode.Normal,
      vertLine: { color: cssVar("--line-strong"), labelBackgroundColor: cssVar("--inv") },
      horzLine: { color: cssVar("--line-strong"), labelBackgroundColor: cssVar("--inv") },
    },
    localization: { locale: "tr-TR" },
  }
}

/** Candles + strategy lines + trade markers + open-position price lines. */
export function PriceChart({ data, scheme, fitKey }: { data: ChartData | null; scheme: string; fitKey: string }) {
  const el = React.useRef<HTMLDivElement>(null)
  const chart = React.useRef<IChartApi | null>(null)
  const candles = React.useRef<ISeriesApi<"Candlestick"> | null>(null)
  const lines = React.useRef<Record<string, ISeriesApi<"Line">>>({})
  const priceLines = React.useRef<IPriceLine[]>([])
  const fitted = React.useRef(false)

  // (re)create on mount and when the colour scheme changes
  React.useEffect(() => {
    if (!el.current) return
    const c = createChart(el.current, { autoSize: true, ...chartTheme() })
    candles.current = c.addCandlestickSeries({
      upColor: cssVar("--up"),
      downColor: cssVar("--down"),
      borderVisible: false,
      wickUpColor: cssVar("--up"),
      wickDownColor: cssVar("--down"),
    })
    chart.current = c
    lines.current = {}
    priceLines.current = []
    fitted.current = false
    return () => {
      c.remove()
      chart.current = null
    }
  }, [scheme])

  React.useEffect(() => {
    const c = chart.current
    const s = candles.current
    if (!c || !s || !data) return
    s.setData(data.candles.map((k) => ({ ...k, time: k.time as Time })))

    for (const [name, series] of Object.entries(lines.current)) {
      if (!(name in data.lines)) {
        c.removeSeries(series)
        delete lines.current[name]
      }
    }
    for (const [name, points] of Object.entries(data.lines)) {
      const st = LINE_STYLE[name] ?? { color: "--muted", dashed: false, width: 1 }
      if (!lines.current[name]) {
        lines.current[name] = c.addLineSeries({
          color: cssVar(st.color),
          lineWidth: st.width,
          lineStyle: st.dashed ? LineStyle.Dashed : LineStyle.Solid,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        })
      }
      lines.current[name].setData(points.map((p) => ({ time: p.time as Time, value: p.value })))
    }

    const markers: SeriesMarker<Time>[] = data.markers.map((m) => {
      const paper = m.source === "paper"
      const color = paper ? (m.kind === "entry" || (m.pnl_pct ?? 0) > 0 ? cssVar("--up") : cssVar("--down")) : cssVar("--faint")
      return m.kind === "entry"
        ? { time: m.time as Time, position: "belowBar", shape: "arrowUp", color, text: paper ? "AL" : "" }
        : { time: m.time as Time, position: "aboveBar", shape: "arrowDown", color, text: paper ? "SAT " + pct(m.pnl_pct, 1) : "" }
    })
    s.setMarkers(markers)

    for (const pl of priceLines.current) s.removePriceLine(pl)
    priceLines.current = []
    const p = data.position
    if (p) {
      const add = (price: number, color: string, title: string) =>
        priceLines.current.push(s.createPriceLine({ price, color, lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: true, title }))
      add(p.entry_price, cssVar("--muted"), "Giriş")
      add(p.stop, cssVar("--down"), "Stop")
      if (p.take_profit) add(p.take_profit, cssVar("--up"), "Hedef")
    }
    if (!fitted.current) {
      c.timeScale().fitContent()
      fitted.current = true
    }
  }, [data, scheme])

  // a new bot or range: fit the whole range once its data has arrived
  React.useEffect(() => {
    fitted.current = false
  }, [fitKey])

  return <div ref={el} className="h-[340px] w-full sm:h-[440px]" />
}
