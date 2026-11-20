import { ArrowLeft, BellOff, Check, CircleAlert } from "lucide-react"
import React from "react"

import { Frame } from "@/components/frame"
import { Logo } from "@/components/header"
import { BotPicker, EventsPicker } from "@/components/subscribe"
import { api, type Events, type SiteConfig, type Subscription } from "@/lib/api"

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <>
      <header className="border-b border-line bg-paper/85 backdrop-blur-md">
        <div className="mx-auto flex max-w-[760px] items-center justify-between px-4 py-3 sm:px-6">
          <a href="/" className="flex items-center gap-2.5 text-ink">
            <span className="grid size-8 place-items-center bg-inv text-inv-ink">
              <Logo className="size-4.5" />
            </span>
            <span className="text-[15px] font-semibold tracking-tight">Kripto Sinyal</span>
          </a>
          <a href="/" className="inline-flex items-center gap-1.5 text-[13px] text-muted hover:text-ink">
            <ArrowLeft className="size-3.5" /> Panele dön
          </a>
        </div>
      </header>
      <main className="mx-auto max-w-[760px] px-4 py-10 sm:px-6">{children}</main>
    </>
  )
}

function Notice({ tone, children }: { tone: "up" | "down" | "neutral"; children: React.ReactNode }) {
  const Icon = tone === "up" ? Check : CircleAlert
  return (
    <div className={"mb-6 flex items-start gap-3 border p-4 text-[14px] " + (tone === "up" ? "border-line bg-up-bg" : tone === "down" ? "border-line bg-down-bg" : "border-line bg-paper")}>
      <Icon className={"mt-0.5 size-4 shrink-0 " + (tone === "up" ? "text-up" : tone === "down" ? "text-down" : "text-muted")} />
      <div>{children}</div>
    </div>
  )
}

/** /abonelik?token=…  — confirm result, change preferences, unsubscribe. */
export function ManagePage() {
  const q = new URLSearchParams(location.search)
  const token = q.get("token") ?? ""
  const status = q.get("durum")
  const [askLeave, setAskLeave] = React.useState(q.get("cik") === "1")
  const [sub, setSub] = React.useState<Subscription | null>(null)
  const [config, setConfig] = React.useState<SiteConfig | null>(null)
  const [bots, setBots] = React.useState<string[]>([])
  const [events, setEvents] = React.useState<Events>("all")
  const [phase, setPhase] = React.useState<"loading" | "ready" | "missing" | "saved" | "left">(token ? "loading" : "missing")
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    api<SiteConfig>("/api/config").then(setConfig).catch(() => {})
    if (!token) return
    api<Subscription>(`/api/subscriptions/${encodeURIComponent(token)}`)
      .then((s) => {
        setSub(s)
        setBots(s.bots)
        setEvents(s.events)
        setPhase("ready")
      })
      .catch(() => setPhase("missing"))
  }, [token])

  const save = async () => {
    setError(null)
    try {
      const s = await api<Subscription>(`/api/subscriptions/${encodeURIComponent(token)}`, { method: "PUT", body: { bots, events } })
      setSub(s)
      setPhase("saved")
    } catch (e) {
      setError((e as Error).message)
    }
  }
  const leave = async () => {
    setError(null)
    try {
      await api(`/api/subscriptions/${encodeURIComponent(token)}`, { method: "DELETE" })
      setPhase("left")
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <Shell>
      <div className="mb-1 font-mono text-[11px] tracking-[0.06em] text-faint">bildirim tercihleri</div>
      <h1 className="mb-6 text-[28px] font-medium tracking-[-0.02em]">Aboneliğin</h1>

      {status === "onaylandi" && phase !== "left" && (
        <Notice tone="up">
          <b>Aboneliğin onaylandı.</b> Seçtiğin bot işleme girdiğinde sana e-posta göndereceğiz.
        </Notice>
      )}

      {phase === "loading" && <p className="text-muted">Yükleniyor…</p>}

      {phase === "missing" && (
        <Notice tone="down">
          <b>Bu link geçersiz ya da abonelik silinmiş.</b>
          <p className="mt-1 text-muted">
            Tekrar abone olmak için{" "}
            <a href="/#bildirim" className="text-ink underline underline-offset-2">
              ana sayfadaki formu
            </a>{" "}
            kullan.
          </p>
        </Notice>
      )}

      {phase === "left" && (
        <Notice tone="neutral">
          <b>Abonelikten çıktın.</b>
          <p className="mt-1 text-muted">Adresin silindi; artık bildirim gelmeyecek.</p>
        </Notice>
      )}

      {(phase === "ready" || phase === "saved") && sub && (
        <>
          {askLeave ? (
            <Frame innerClassName="p-5 sm:p-6">
              <BellOff className="mb-3 size-5" />
              <h2 className="text-lg font-semibold">Abonelikten çıkmak istiyor musun?</h2>
              <p className="mt-1 text-[14px] text-muted">
                <b className="text-ink">{sub.address}</b> adresine hiçbir bildirim gitmez ve adresin silinir.
              </p>
              <div className="mt-5 flex flex-wrap gap-3">
                <button type="button" onClick={leave} className="bg-inv px-4 py-2.5 text-[14px] font-semibold text-inv-ink hover:opacity-90">
                  Evet, abonelikten çık
                </button>
                <button type="button" onClick={() => setAskLeave(false)} className="border border-line-strong px-4 py-2.5 text-[14px] hover:border-ink">
                  Vazgeç, tercihlerimi değiştireyim
                </button>
              </div>
            </Frame>
          ) : (
            <Frame innerClassName="grid gap-6 p-5 sm:p-6">
              <div className="flex flex-wrap items-baseline justify-between gap-2 text-[14px]">
                <span>
                  <span className="text-muted">{sub.channel === "email" ? "E-posta" : "Telegram"}:</span> <b>{sub.address}</b>
                </span>
                {!sub.confirmed && <span className="text-[12.5px] text-down">Henüz onaylanmadı — maildeki linke tıkla</span>}
              </div>
              {config && <BotPicker bots={config.bots} value={bots} onChange={setBots} />}
              <EventsPicker value={events} onChange={setEvents} />
              {error && <p className="text-[13px] text-down">{error}</p>}
              {phase === "saved" && (
                <p className="inline-flex items-center gap-1.5 text-[13px] text-up">
                  <Check className="size-4" /> Kaydedildi
                </p>
              )}
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5">
                <button
                  type="button"
                  onClick={save}
                  disabled={!bots.length}
                  className="bg-inv px-4 py-2.5 text-[14px] font-semibold text-inv-ink hover:opacity-90 disabled:opacity-50"
                >
                  Tercihleri kaydet
                </button>
                <button type="button" onClick={() => setAskLeave(true)} className="text-[13px] text-muted underline underline-offset-2 hover:text-down">
                  Abonelikten çık
                </button>
              </div>
            </Frame>
          )}
        </>
      )}
    </Shell>
  )
}

/** /gizlilik — KVKK aydınlatma metni (information notice). */
export function PrivacyPage() {
  const [config, setConfig] = React.useState<SiteConfig | null>(null)
  React.useEffect(() => {
    api<SiteConfig>("/api/config").then(setConfig).catch(() => {})
  }, [])
  const contact = config?.contact_email
  const H = ({ children }: { children: React.ReactNode }) => <h2 className="mt-8 mb-2 text-[17px] font-semibold tracking-tight">{children}</h2>
  return (
    <Shell>
      <div className="mb-1 font-mono text-[11px] tracking-[0.06em] text-faint">kvkk</div>
      <h1 className="mb-2 text-[28px] font-medium tracking-[-0.02em]">Aydınlatma metni</h1>
      <p className="text-[13px] text-muted">6698 sayılı Kişisel Verilerin Korunması Kanunu kapsamında</p>
      <Frame className="mt-6" innerClassName="p-5 text-[14.5px] leading-relaxed text-soft sm:p-7">
        <H>Hangi veriyi topluyoruz?</H>
        <p>
          Telegram botuna abone olursan <b>Telegram sohbet kimliğini</b> (bir numara), seçtiğin botları ve bildirim türünü saklarız.
          {config?.email_enabled && " E-posta ile kaydolursan e-posta adresini de saklarız."} Adını, telefon numaranı, konumunu ya da ödeme
          bilgisini almayız. Sitede reklam veya takip çerezi yoktur.
        </p>
        <H>Ne için kullanıyoruz?</H>
        <p>
          Sadece seçtiğin botlar işleme girdiğinde ya da çıktığında sana bildirim göndermek ve aboneliğini yönetmen için. Adresini kimseyle
          paylaşmayız, satmayız, reklam için kullanmayız.
        </p>
        <H>Hukuki sebep</H>
        <p>
          Açık rızan (KVKK m. 5/1). Rızanı botta <code className="font-mono text-[13px]">/abone</code> yazarak
          {config?.email_enabled && " ya da e-postadaki onay linkine tıklayarak"} verirsin;{" "}
          <code className="font-mono text-[13px]">/iptal</code> ile istediğin an geri alırsın.
        </p>
        <H>Ne kadar saklıyoruz?</H>
        <p>
          Abone olduğun sürece. <code className="font-mono text-[13px]">/iptal</code> yazdığında ya da botu engellediğinde kaydın hemen
          silinir. Gönderilmiş bildirim kayıtları 30 gün sonra otomatik silinir.
        </p>
        <H>Veriler nerede?</H>
        <p>
          Sitenin çalıştığı sunucuda saklanır. Bildirimler Telegram üzerinden iletilir{config?.email_enabled && ", e-postalar bir e-posta gönderim hizmeti aracılığıyla"};
          bu yurt dışına aktarım açık rızan kapsamındadır.
        </p>
        <H>Hakların</H>
        <p>
          KVKK m. 11 kapsamında verilerine erişme, düzeltme ve silinmesini isteme hakkın var. Botta{" "}
          <code className="font-mono text-[13px]">/aboneliklerim</code> ile kayıtlı bilgini görebilir,{" "}
          <code className="font-mono text-[13px]">/iptal</code> ile silebilirsin.
          {contact && (
            <>
              {" "}
              Diğer talepler için:{" "}
              <a className="text-ink underline underline-offset-2" href={`mailto:${contact}`}>
                {contact}
              </a>
            </>
          )}
        </p>
        <H>Önemli</H>
        <p>
          Bu site eğitim amaçlıdır. Botlar sanal bakiyeyle işlem yapar (paper trading); gerçek emir gönderilmez. Bildirimler ve sitedeki hiçbir
          içerik yatırım tavsiyesi değildir.
        </p>
      </Frame>
    </Shell>
  )
}
