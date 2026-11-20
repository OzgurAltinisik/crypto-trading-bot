import { BellRing, Check, Mail, Send } from "lucide-react"
import React from "react"

import { Frame, SectionTitle } from "@/components/frame"
import { api, type Events, type SiteConfig } from "@/lib/api"
import { cn } from "@/lib/utils"

/* ------------------------------------------------------------ shared inputs */

export function BotPicker({
  bots,
  value,
  onChange,
}: {
  bots: SiteConfig["bots"]
  value: string[]
  onChange: (v: string[]) => void
}) {
  const toggle = (id: string) => onChange(value.includes(id) ? value.filter((v) => v !== id) : [...value, id])
  return (
    <fieldset>
      <legend className="mb-2 text-[13px] font-medium">Hangi botlar?</legend>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {bots.map((b) => {
          const on = value.includes(b.id)
          return (
            <label
              key={b.id}
              className={cn(
                "flex cursor-pointer items-center justify-between gap-2 border px-3 py-2 text-[13px] transition-colors select-none",
                on ? "border-ink bg-raise" : "border-line bg-paper text-muted hover:border-line-strong",
              )}
            >
              <span>
                <span className={cn("font-semibold", on && "text-ink")}>{b.symbol.split("/")[0]}</span>
                <span className="block text-[11px] text-faint">{b.strategy === "donchian" ? "Donchian" : "EMA 50/200"}</span>
              </span>
              <input type="checkbox" className="sr-only" checked={on} onChange={() => toggle(b.id)} />
              <span className={cn("grid size-4 place-items-center border", on ? "border-ink bg-ink text-inv-ink" : "border-line-strong")}>
                {on && <Check className="size-3" strokeWidth={3} />}
              </span>
            </label>
          )
        })}
      </div>
    </fieldset>
  )
}

export function EventsPicker({ value, onChange }: { value: Events; onChange: (v: Events) => void }) {
  const options: [Events, string, string][] = [
    ["all", "Alım + satım", "Pozisyon açılınca ve kapanınca"],
    ["entry", "Sadece alımlar", "Sadece bot işleme girince"],
  ]
  return (
    <fieldset>
      <legend className="mb-2 text-[13px] font-medium">Ne zaman haber verelim?</legend>
      <div className="grid gap-2 sm:grid-cols-2">
        {options.map(([v, title, sub]) => (
          <label
            key={v}
            className={cn(
              "flex cursor-pointer items-start gap-2.5 border px-3 py-2 text-[13px] transition-colors select-none",
              value === v ? "border-ink bg-raise" : "border-line bg-paper text-muted hover:border-line-strong",
            )}
          >
            <input type="radio" name="events" className="sr-only" checked={value === v} onChange={() => onChange(v)} />
            <span className={cn("mt-0.5 grid size-4 shrink-0 place-items-center rounded-full border", value === v ? "border-ink" : "border-line-strong")}>
              {value === v && <span className="size-2 rounded-full bg-ink" />}
            </span>
            <span>
              <span className={cn("font-semibold", value === v && "text-ink")}>{title}</span>
              <span className="block text-[11.5px] text-faint">{sub}</span>
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  )
}

/* ------------------------------------------------------------ section */

export function SubscribeSection({ config, defaultBot }: { config: SiteConfig | null; defaultBot: string | null }) {
  const [email, setEmail] = React.useState("")
  const [bots, setBots] = React.useState<string[]>([])
  const [events, setEvents] = React.useState<Events>("all")
  const [consent, setConsent] = React.useState(false)
  const [website, setWebsite] = React.useState("") // honeypot
  const [state, setState] = React.useState<{ kind: "idle" | "sending" | "done" | "error"; message?: string }>({ kind: "idle" })

  // preselect the bot the visitor is looking at
  React.useEffect(() => {
    if (defaultBot && bots.length === 0) setBots([defaultBot])
  }, [defaultBot, bots.length])

  const emailOn = config?.email_enabled ?? false
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!bots.length) return setState({ kind: "error", message: "En az bir bot seç." })
    if (!consent) return setState({ kind: "error", message: "Devam etmek için aydınlatma metnini onayla." })
    setState({ kind: "sending" })
    try {
      const r = await api<{ message: string }>("/api/subscriptions", { method: "POST", body: { email, bots, events, website } })
      setState({ kind: "done", message: r.message })
    } catch (err) {
      setState({ kind: "error", message: (err as Error).message })
    }
  }

  // Telegram-only site (no SMTP configured): one wide Telegram block instead of the form
  if (config && !emailOn) return <TelegramOnly bot={config.telegram_bot} />

  return (
    <section id="bildirim">
      <SectionTitle eyebrow="bildirim" title="Bot işleme girince haberin olsun" />
      <div className="grid gap-6 lg:grid-cols-[1.5fr_1fr]">
        <Frame innerClassName="p-4 sm:p-6">
          <div className="mb-5 flex items-start gap-3">
            <span className="grid size-9 shrink-0 place-items-center bg-inv text-inv-ink">
              <Mail className="size-4" />
            </span>
            <div>
              <h3 className="text-[15px] font-semibold">E-posta ile</h3>
              <p className="text-[13px] text-muted">Hesap yok, şifre yok. Onay linkine tıklarsın, istediğin zaman tek tıkla çıkarsın.</p>
            </div>
          </div>

          {state.kind === "done" ? (
            <div className="flex items-start gap-3 border border-line bg-up-bg p-4 text-[14px]">
              <Check className="mt-0.5 size-4 shrink-0 text-up" />
              <div>
                <b>Neredeyse tamam!</b>
                <p className="mt-1 text-muted">{state.message}</p>
                <button type="button" className="mt-3 text-[13px] underline underline-offset-2" onClick={() => setState({ kind: "idle" })}>
                  Başka bir adres ekle
                </button>
              </div>
            </div>
          ) : (
            <form onSubmit={submit} className="grid gap-5" noValidate>
              <div>
                <label htmlFor="sub-email" className="mb-2 block text-[13px] font-medium">
                  E-posta adresin
                </label>
                <input
                  id="sub-email"
                  type="email"
                  required
                  autoComplete="email"
                  inputMode="email"
                  placeholder="ornek@gmail.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  disabled={!emailOn}
                  className="w-full border border-line-strong bg-paper px-3 py-2.5 text-[15px] outline-none placeholder:text-faint focus:border-ink disabled:opacity-60"
                />
              </div>
              {config && <BotPicker bots={config.bots} value={bots} onChange={setBots} />}
              <EventsPicker value={events} onChange={setEvents} />

              {/* honeypot: hidden from people, bots fill it in */}
              <input
                type="text"
                tabIndex={-1}
                autoComplete="off"
                aria-hidden="true"
                className="absolute -left-[9999px] h-0 w-0 opacity-0"
                value={website}
                onChange={(e) => setWebsite(e.target.value)}
                name="website"
              />

              <label className="flex cursor-pointer items-start gap-2.5 text-[12.5px] text-muted select-none">
                <input type="checkbox" className="mt-0.5 size-3.5 accent-[var(--ink)]" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
                <span>
                  E-posta adresimin sadece bot bildirimleri için kullanılacağını belirten{" "}
                  <a href="/gizlilik" className="text-ink underline underline-offset-2">
                    aydınlatma metnini
                  </a>{" "}
                  okudum. Bildirimler yatırım tavsiyesi değildir.
                </span>
              </label>

              {state.kind === "error" && <p className="text-[13px] text-down">{state.message}</p>}
              {!emailOn && <p className="text-[13px] text-muted">E-posta bildirimleri şu an kapalı. Telegram ile abone olabilirsin.</p>}

              <button
                type="submit"
                disabled={!emailOn || state.kind === "sending"}
                className="inline-flex items-center justify-center gap-2 bg-inv px-4 py-3 text-[14px] font-semibold text-inv-ink transition-opacity hover:opacity-90 disabled:opacity-50 sm:justify-self-start"
              >
                <BellRing className="size-4" />
                {state.kind === "sending" ? "Gönderiliyor…" : "Bildirimleri aç"}
              </button>
            </form>
          )}
        </Frame>

        <Frame innerClassName="flex h-full flex-col p-4 sm:p-6">
          <div className="mb-5 flex items-start gap-3">
            <span className="grid size-9 shrink-0 place-items-center border border-line-strong bg-paper">
              <Send className="size-4" />
            </span>
            <div>
              <h3 className="text-[15px] font-semibold">Telegram ile</h3>
              <p className="text-[13px] text-muted">Anında gelir, e-posta gerekmez.</p>
            </div>
          </div>
          {config?.telegram_bot ? (
            <>
              <ol className="grid gap-3 text-[13.5px]">
                <li className="flex gap-3">
                  <span className="font-mono text-faint">01</span>
                  <span>
                    Botu aç:{" "}
                    <a className="font-semibold underline underline-offset-2" href={`https://t.me/${config.telegram_bot}`} target="_blank" rel="noreferrer">
                      @{config.telegram_bot}
                    </a>
                  </span>
                </li>
                <li className="flex gap-3">
                  <span className="font-mono text-faint">02</span>
                  <span>
                    Yaz: <code className="bg-card px-1.5 py-0.5 font-mono text-[12.5px]">/abone btc</code> ya da{" "}
                    <code className="bg-card px-1.5 py-0.5 font-mono text-[12.5px]">/abone hepsi</code>
                  </span>
                </li>
                <li className="flex gap-3">
                  <span className="font-mono text-faint">03</span>
                  <span>
                    Sadece alımlar için sona <code className="bg-card px-1.5 py-0.5 font-mono text-[12.5px]">alim</code> ekle; durdurmak için{" "}
                    <code className="bg-card px-1.5 py-0.5 font-mono text-[12.5px]">/iptal</code>
                  </span>
                </li>
              </ol>
              <a
                href={`https://t.me/${config.telegram_bot}?start=abone`}
                target="_blank"
                rel="noreferrer"
                className="mt-6 inline-flex items-center justify-center gap-2 border border-ink px-4 py-2.5 text-[14px] font-semibold hover:bg-raise sm:mt-auto sm:justify-self-start"
              >
                <Send className="size-4" /> Telegram'da aç
              </a>
            </>
          ) : (
            <p className="text-[13px] text-muted">Telegram botu yakında.</p>
          )}
        </Frame>
      </div>
    </section>
  )
}

/* ------------------------------------------------------------ telegram only */

const COMMANDS: [string, string][] = [
  ["/abone btc", "BTC botu işleme girince ve çıkınca haber ver"],
  ["/abone hepsi", "Bütün botlardan haber al"],
  ["/abone eth alim", "Sadece alımlarda haber ver"],
  ["/durum btc", "BTC botu şu an ne durumda?"],
  ["/durum", "Bütün botların durumu"],
  ["/iptal btc · /iptal", "Bir botu ya da hepsini durdur"],
]

function TelegramOnly({ bot }: { bot: string | null }) {
  return (
    <section id="bildirim">
      <SectionTitle eyebrow="bildirim" title="Bot işleme girince Telegram'dan haberin olsun" />
      <Frame innerClassName="grid gap-8 p-5 sm:p-7 lg:grid-cols-[1fr_1.2fr]">
        <div className="flex flex-col">
          <span className="mb-4 grid size-10 place-items-center bg-inv text-inv-ink">
            <Send className="size-5" />
          </span>
          <h3 className="text-[22px] font-medium tracking-[-0.02em]">Hesap yok, form yok.</h3>
          <p className="mt-2 max-w-md text-[14.5px] leading-relaxed text-muted">
            Telegram botunu aç, takip etmek istediğin coini yaz. Bot işleme girdiği an telefonuna bildirim gelir. İstediğin zaman{" "}
            <code className="bg-card px-1.5 py-0.5 font-mono text-[12.5px] text-ink">/iptal</code> yazıp durdurursun.
          </p>
          {bot ? (
            <a
              href={`https://t.me/${bot}`}
              target="_blank"
              rel="noreferrer"
              className="mt-6 inline-flex items-center justify-center gap-2 self-start bg-inv px-5 py-3 text-[15px] font-semibold text-inv-ink hover:opacity-90"
            >
              <Send className="size-4" /> @{bot} botunu aç
            </a>
          ) : (
            <p className="mt-6 text-[13px] text-muted">Telegram botu yakında.</p>
          )}
          <p className="mt-auto pt-6 text-[12px] text-faint">
            Sadece Telegram sohbet kimliğin saklanır.{" "}
            <a href="/gizlilik" className="underline underline-offset-2 hover:text-ink">
              Aydınlatma metni
            </a>{" "}
            · Bildirimler yatırım tavsiyesi değildir.
          </p>
        </div>
        <div>
          <div className="mb-2 font-mono text-[11px] tracking-[0.06em] text-faint">komutlar</div>
          <ul className="divide-y divide-line border border-line bg-paper">
            {COMMANDS.map(([cmd, desc]) => (
              <li key={cmd} className="flex flex-col gap-0.5 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
                <code className="font-mono text-[13px] font-medium text-ink">{cmd}</code>
                <span className="text-[13px] text-muted sm:text-right">{desc}</span>
              </li>
            ))}
          </ul>
        </div>
      </Frame>
    </section>
  )
}
