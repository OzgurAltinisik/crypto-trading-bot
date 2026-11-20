import InkOrbitFeatures from "@/components/ui/ink-orbit-features"
import type { Backtest } from "@/lib/api"

const DIAMOND = "M12 2.5 21.5 12 12 21.5 2.5 12zM12 7.5 7.5 12 12 16.5 16.5 12z"

/** Monthly closing balances from the backtest equity curve (real data, not a forecast). */
function monthly(bt: Backtest | null): number[] {
  if (!bt || bt.equity.length < 2) return []
  const byMonth = new Map<string, number>()
  for (const p of bt.equity) {
    const d = new Date(p.time * 1000)
    byMonth.set(d.getUTCFullYear() + "-" + d.getUTCMonth(), p.value)
  }
  return [bt.equity[0].value, ...byMonth.values()]
}

/** "How it works" section built on the ink-orbit features bento. */
export function HowItWorks({ bt, botLabel }: { bt: Backtest | null; botLabel: string }) {
  const values = monthly(bt)
  return (
    <div id="nasil">
      <InkOrbitFeatures
        theme="auto"
        brand="Kripto Sinyal"
        markPath={DIAMOND}
        team={["Sen · panelde", "Arkadaş · BTC grafiğinde", "Arkadaş · ETH'yi izliyor", "Arkadaş · backtest'e bakıyor", "Arkadaş · çevrimdışı"]}
        tag="Nasıl çalışır"
        title={"Tek motor,\n*herkes için* aynı veri"}
        collaboration={{
          title: "Davet linkiyle paylaşılan panel",
          description: "Linki gönderdiğin herkes aynı sinyalleri, açık pozisyonları ve sonuçları canlı görür. Kimse ayar değiştiremez.",
        }}
        reports={{
          title: "Her karar kayıt altında",
          description: "Motor her mum kapandığında karar verir. Her sinyal ve işlem veritabanına yazılır, Telegram'a bildirilir.",
          label: "İŞLEM #",
        }}
        integrations={{
          title: "Bağlı servisler",
          description: "Binance'ten canlı fiyat, Telegram bildirimleri, SQLite kayıt ve bu panel. API anahtarı gerekmez, emir gönderilmez.",
          tools: ["Binance", "Telegram", "SQLite", "Panel"],
          syncingLabel: "senkron · ",
          idleLabel: "4 bağlı",
        }}
        insights={{
          title: "Backtest ile sınandı",
          description: `${botLabel} botunun 2024'ten bu yana aylık bakiyesi, gerçek geçmiş veriyle. Tahmin değildir; geçmiş performans gelecek için garanti değildir.`,
          values: values.length > 2 ? values : [10, 10, 10],
          forecastFrom: null,
          pointLabel: "ay ",
        }}
      />
    </div>
  )
}
