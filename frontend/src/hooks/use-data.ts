import React from "react"

import { api, ApiError } from "@/lib/api"

/** Fetch `path` now and every `everyMs` (paused while the tab is hidden). */
export function usePoll<T>(path: string | null, everyMs: number) {
  const [data, setData] = React.useState<T | null>(null)
  const [error, setError] = React.useState<ApiError | Error | null>(null)
  const [loading, setLoading] = React.useState(false)

  React.useEffect(() => {
    if (!path) return
    let alive = true
    const load = async () => {
      if (document.hidden) return
      setLoading(true)
      try {
        const d = await api<T>(path)
        if (alive) {
          setData(d)
          setError(null)
        }
      } catch (e) {
        if (alive) setError(e as Error)
      } finally {
        if (alive) setLoading(false)
      }
    }
    setData(null)
    load()
    const t = everyMs > 0 ? setInterval(load, everyMs) : undefined
    const onVisible = () => !document.hidden && load()
    document.addEventListener("visibilitychange", onVisible)
    return () => {
      alive = false
      if (t) clearInterval(t)
      document.removeEventListener("visibilitychange", onVisible)
    }
  }, [path, everyMs])

  return { data, error, loading }
}

/** "dark" | "light", following the OS setting. */
export function useScheme() {
  const q = "(prefers-color-scheme: dark)"
  const [dark, setDark] = React.useState(() => window.matchMedia(q).matches)
  React.useEffect(() => {
    const m = window.matchMedia(q)
    const on = () => setDark(m.matches)
    m.addEventListener("change", on)
    return () => m.removeEventListener("change", on)
  }, [])
  return dark ? "dark" : "light"
}
