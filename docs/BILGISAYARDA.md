# Kendi bilgisayarında çalıştırma (deneme için, VPS'siz)

Bot ve site **senin Windows bilgisayarında** çalışır; Cloudflare'in ücretsiz tüneli siteye internetten `https://xxxx.trycloudflare.com` adresiyle ulaşılmasını sağlar. Modem ayarı veya port açmak gerekmez.

> Bu yöntem **deneme** içindir. Bilgisayar kapanırsa, uykuya geçerse ya da internet kesilirse site kapanır ve bot işlem kaçırabilir. Adres her başlatmada değişir. Kalıcı kullanım için [KURULUM.md](KURULUM.md) (VPS).

## Gerekenler (bir kez)

| Program | Nasıl |
|---|---|
| Python 3.12+ | Muhtemelen var. Yoksa [python.org](https://www.python.org/downloads/), kurarken **Add to PATH** işaretle |
| Node.js (LTS) | Muhtemelen var. Yoksa [nodejs.org](https://nodejs.org) |
| cloudflared | Bir terminalde: `winget install --id Cloudflare.cloudflared` (sonra terminali kapatıp yeniden aç) |

> Proje klasörünün yolu **kısa** olmalı (örn. `C:\kripto-sinyal`). Windows'ta çok uzun yollarda Python paketleri kurulamıyor.

## 1. Telegram botunu oluştur

1. Telegram'da [@BotFather](https://t.me/BotFather)'a yaz: `/newbot`
2. Bir ad ver (örn. *Kripto Sinyal*), sonra `bot` ile biten bir kullanıcı adı (örn. `KriptoSinyalBot`).
3. BotFather sana bir **token** verir (`123456789:AAH...`). Bu şifre gibidir; kimseyle paylaşma, sohbete de yapıştırma.

## 2. Kurulum

1. `scripts\windows\kurulum.bat` dosyasına **çift tıkla**. Python ortamını kurar, siteyi derler ve `.env` dosyasını oluşturur (ilk seferde birkaç dakika sürer).
2. Proje klasöründe `.env` dosyasını Not Defteri ile aç ve şu iki satırı doldur:

```ini
TELEGRAM_TOKEN=123456789:AAH...           # BotFather'ın verdiği token
TELEGRAM_BOT_USERNAME=KriptoSinyalBot     # @ olmadan
```

Diğer satırlara dokunma. `SMTP_...` satırları boş kalacak (e-posta kapalı, sadece Telegram). `DOMAIN` ve `PUBLIC_URL`'i başlatma scripti kendisi ayarlar.

## 3. Başlat

`scripts\windows\baslat.bat` dosyasına **çift tıkla**. Birkaç saniye sonra pencerede şöyle bir satır çıkar:

```
  Site adresi (panoya kopyalandı):
  https://ornek-kelimeler-1234.trycloudflare.com
```

- Bu adresi tarayıcında aç: site orada.
- Telegram'da botuna `/abone btc` yaz; `/durum` ile durumu gör.
- Adresi arkadaşlarına gönder. Onlar sadece linke tıklar ve botu açar, hiçbir şey kurmaz.

**Pencereyi kapatma.** Pencere açık kaldığı sürece bilgisayar uykuya geçmez. Durdurmak için pencerede `Ctrl+C`.

## Bilmen gerekenler

- **Adres her başlatmada değişir.** Yeniden başlatınca arkadaşlarına yeni linki gönder. (Telegram botu değişmez; abonelikler kaybolmaz.)
- **Dizüstü bilgisayarda kapağı kapatınca** Windows uyuyabilir. Denemede kapağı açık bırak ya da Ayarlar → Sistem → Güç bölümünden "kapak kapatılınca hiçbir şey yapma" seç.
- **Windows güncellemesi** bilgisayarı yeniden başlatabilir; sonra `baslat.bat`'ı tekrar çalıştır. Kaçırılan mumlar açılışta işlenir, stop seviyeleri de kontrol edilir.
- **Veriler** `data\` klasöründe (`bot.db`). VPS'e geçerken bu dosyayı taşırsan geçmiş işlemler ve aboneler korunur.
- **Loglar:** `data\logs\engine.log` (bot), `data\logs\tunnel.log` (tünel).

## Sorun giderme

| Belirti | Çözüm |
|---|---|
| `kurulum.bat`: "Klasör yolu çok uzun" | Projeyi `C:\kripto-sinyal` gibi kısa bir yere taşı |
| `baslat.bat`: "cloudflared yok" | `winget install --id Cloudflare.cloudflared`, sonra yeni pencere |
| "Tünel adresi alınamadı" | İnternet bağlantısını kontrol et, `data\logs\tunnel.log`'a bak, tekrar dene |
| Bot Telegram'da cevap vermiyor | `.env`'deki token doğru mu? Aynı token başka bir yerde (eski VPS gibi) çalışıyorsa onu kapat |
| Site açılıyor ama "Motor durdu" yazıyor | Pencerede hata var mı bak; `data\logs\engine.log` |
