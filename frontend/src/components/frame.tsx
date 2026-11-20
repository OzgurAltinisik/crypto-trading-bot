import React from "react"

import { cn } from "@/lib/utils"

/** A paper card with the ink-orbit corner brackets. */
export function Frame({
  className,
  innerClassName,
  hover = false,
  active = false,
  as: Tag = "div",
  children,
  ...rest
}: {
  className?: string
  innerClassName?: string
  hover?: boolean
  active?: boolean
  as?: "div" | "section" | "button"
  children: React.ReactNode
} & React.HTMLAttributes<HTMLElement>) {
  return (
    <Tag className={cn("frame", hover && "frame-hover", active && "frame-active", className)} {...(rest as object)}>
      <span className="bk bk-tl" aria-hidden="true" />
      <span className="bk bk-tr" aria-hidden="true" />
      <span className="bk bk-bl" aria-hidden="true" />
      <span className="bk bk-br" aria-hidden="true" />
      <div
        className={cn(
          "h-full border border-line bg-gradient-to-b from-raise to-card transition-[border-color,box-shadow] duration-300",
          hover && "hover:border-line-strong hover:shadow-ink",
          active && "border-line-strong shadow-ink",
          innerClassName,
        )}
      >
        {children}
      </div>
    </Tag>
  )
}

export function SectionTitle({ eyebrow, title, right }: { eyebrow?: string; title: string; right?: React.ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        {eyebrow && <div className="mb-1 font-mono text-[11px] tracking-[0.06em] text-faint">{eyebrow}</div>}
        <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
      </div>
      {right}
    </div>
  )
}

export function Tag({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "up" | "down" | "ink" }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 border px-2 py-0.5 text-[11.5px] font-medium whitespace-nowrap",
        tone === "neutral" && "border-line bg-card text-soft",
        tone === "up" && "border-transparent bg-up-bg text-up",
        tone === "down" && "border-transparent bg-down-bg text-down",
        tone === "ink" && "border-transparent bg-inv text-inv-ink",
      )}
    >
      {children}
    </span>
  )
}
