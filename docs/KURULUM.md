# Sunucuya kurulum (Hetzner + Docker)

> Önce kendi bilgisayarında denemek için: [BILGISAYARDA.md](BILGISAYARDA.md)

Bu rehber botları ve siteyi bir Ubuntu sunucusunda 7/24 çalıştırır. **Sunucuyu sadece sen kurarsın.** Kullanıcılar hiçbir şey kurmaz: siteye girerler, isterlerse e-posta ya da Telegram ile bildirime abone olurlar.

Kurulumdan sonra çalışan servisler:

- **motor** (`engine`): sinyalleri üretir; abonelere e-posta ve Telegram bildirimi gönderir; Telegram komutlarını (`/abone`, `/durum`...) cevaplar
- **site** (`web`): `https://<adres>` üzerinde panel, abonelik formu, tercih ve aydınlatma metni sayfaları
- **Caddy**: HTTPS sertifikasını otomatik alır ve yeniler
- her gece 03:15'te veritabanı yedeği

Toplam süre ~20 dakika. Aylık maliyet: en küçük Hetzner sunucusu (CX22 veya benzeri, 2 vCPU / 4 GB).

---

## 1. Sunucu

1. [Hetzner Cloud Console](https://console.hetzner.cloud) → **Add Server**
2. Konum: Almanya veya Finlandiya · İmaj: **Ubuntu 24.04** · Tip: en küçük paylaşımlı vCPU (CX22)
3. **SSH key** ekle (şifre yerine). Bilgisayarında yoksa: `ssh-keygen -t ed25519`, sonra `~/.ssh/id_ed25519.pub` içeriğini yapıştır.
4. Oluştur, IP adresini not et.

## 2. Site adresi

- **Domain yoksa:** `SUNUCU_IP.sslip.io` adresini kullan (örn. `203.0.113.10.sslip.io`). Bu ücretsiz servis IP'ye işaret eder ve Caddy bunun için de gerçek HTTPS sertifikası alır.
- **Domain alınca:** DNS'e bir **A kaydı** ekle (`kriptosinyal.com → SUNUCU_IP`), `.env`'de `DOMAIN` ve `PUBLIC_URL`'i değiştir, `docker compose up -d` yap.

## 3. Kurulum scripti

```bash
ssh root@SUNUCU_IP
curl -fsSLO https://raw.githubusercontent.com/OzgurAltinisik/crypto-trading-bot/main/deploy/setup-server.sh
less setup-server.sh        # ne yaptığına bir göz at
bash setup-server.sh
```

Script şunları yapar: Docker'ı resmi depodan kurar, güvenlik duvarını açar (sadece SSH, 80, 443), 2 GB swap ekler, repoyu `/opt/cryptobot` klasörüne klonlar, `.env` oluşturur ve günlük yedeği ayarlar. Tekrar çalıştırmak güvenlidir.

> Henüz `main`'e birleştirilmemiş bir branch'i kurmak için: `BRANCH=feat/core-engine bash setup-server.sh`

## 4. E-posta bildirimleri (isteğe bağlı — sadece Telegram istiyorsan bu adımı atla)

Bildirimler herhangi bir SMTP servisiyle gider. Domain yokken en kolayı **sadece bu iş için açacağın** bir Gmail hesabı (günde ~500 mail; birkaç yüz abone için yeter):

1. Yeni bir Gmail hesabı aç (örn. `kriptosinyal.bildirim@gmail.com`). Kişisel hesabını kullanma.
2. Hesapta **2 adımlı doğrulamayı** aç: Google Hesabı → Güvenlik.
3. [Uygulama şifreleri](https://myaccount.google.com/apppasswords) sayfasında "Kripto Sinyal" adıyla bir şifre oluştur; 16 karakterlik şifreyi kopyala.
4. `.env`'ye yaz:

```ini
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=kriptosinyal.bildirim@gmail.com
SMTP_PASSWORD=abcdefghijklmnop          # uygulama şifresi, boşluksuz
MAIL_FROM=kriptosinyal.bildirim@gmail.com
MAIL_FROM_NAME=Kripto Sinyal
```

**Domain alınca** daha iyi teslim oranı için [Brevo](https://www.brevo.com) veya [Resend](https://resend.com) gibi bir servise geç; sadece bu 5 satır değişir (`SMTP_HOST=smtp-relay.brevo.com` gibi), kod değişmez. Servisin istediği SPF/DKIM DNS kayıtlarını eklemeyi unutma.

`SMTP_HOST` boş bırakılırsa sitedeki e-posta formu kapalı görünür, Telegram yine çalışır.

## 5. Telegram botu

1. Telegram'da [@BotFather](https://t.me/BotFather) → `/newbot` → bir ad ve kullanıcı adı ver (örn. `KriptoSinyalBot`), token'ı al.
2. `.env`:

```ini
TELEGRAM_TOKEN=123456:ABC...
TELEGRAM_BOT_USERNAME=KriptoSinyalBot     # @ olmadan; sitedeki "Telegram'da aç" butonu için
```

Bot herkese açıktır (`TELEGRAM_PUBLIC=1`). Kullanıcılar bota şunları yazar:

| Komut | Ne yapar |
|---|---|
| `/abone btc` | BTC botu işleme girince ve çıkınca haber verir |
| `/abone eth alim` | ETH botu için sadece alımlar |
| `/abone hepsi` | tüm botlar |
| `/iptal btc` · `/iptal` | bir botu / hepsini durdurur |
| `/aboneliklerim`, `/durum`, `/pozisyonlar`, `/islemler`, `/botlar`, `/panel` | bilgi |

**İsteğe bağlı:** tüm sinyallerin otomatik düştüğü bir kanal istersen kanal kur, botu **yönetici** yap ve `TELEGRAM_CHAT_ID=@kanal_adi` yaz.

## 6. Ayarlar ve başlatma

```bash
cd /opt/cryptobot
nano .env
```

```ini
DOMAIN=203.0.113.10.sslip.io
PUBLIC_URL=https://203.0.113.10.sslip.io
DASHBOARD_KEY=                           # boş = site herkese açık
CONTACT_EMAIL=kriptosinyal.bildirim@gmail.com   # aydınlatma metnindeki iletişim
# + 4. ve 5. adımdaki SMTP_* ve TELEGRAM_* satırları
```

```bash
docker compose up -d --build              # ilk derleme birkaç dakika sürer
docker compose ps                         # üçü de "running" / "healthy" olmalı
docker compose logs -f engine             # motorun loglarını izle (Ctrl+C ile çık)
```

**Kontrol:** siteyi aç, en alttaki formdan kendi adresinle abone ol. Onay maili gelmeli (gelmezse spam klasörüne bak). Telegram'da bota `/abone btc` yaz.

## 7. Paylaşma

Site herkese açık: `https://<DOMAIN>` linkini paylaşman yeterli. Telefonda Chrome/Safari menüsünden **Ana ekrana ekle** dersen uygulama gibi açılır.

Sadece davetlilerin görmesini istersen `.env`'de `DASHBOARD_KEY`'e uzun rastgele bir değer yaz (`openssl rand -hex 24`) ve `https://<DOMAIN>/?key=<DASHBOARD_KEY>` linkini paylaş. Abonelerin onay/çıkış linkleri anahtar olmadan da çalışır.

---

## Günlük işler

| İş | Komut (`/opt/cryptobot` içinde) |
|---|---|
| Güncelle (yeni kod) | `bash deploy/update.sh` (önce yedek alır) |
| Durum | `docker compose ps` · Telegram'da `/durum` |
| Loglar | `docker compose logs -f engine` / `web` / `caddy` |
| Abone sayısı | `sqlite3 data/bot.db "select channel, count(*) from subscribers where confirmed=1 group by channel"` |
| Gönderilemeyen mailler | `sqlite3 data/bot.db "select id, address, attempts, last_error from outbox where sent_at is null"` |
| Bot ayarını değiştir | `nano config/bots.yaml` → `docker compose up -d --build` |
| Yeniden başlat | `docker compose restart engine` |
| Durdur | `docker compose down` (veriler `data/` içinde kalır) |
| Elle yedek | `bash deploy/backup.sh` → `data/backups/` |

Açık pozisyonlar, bakiyeler ve aboneler `data/bot.db` dosyasında; güncelleme veya yeniden başlatmada kaybolmaz. Bildirimler önce veritabanındaki bir kuyruğa yazılır; mail sunucusu geçici olarak çalışmazsa motor artan aralıklarla tekrar dener, aynı bildirim iki kez gitmez.

## Gizlilik (KVKK)

Site sadece e-posta adresini (ya da Telegram sohbet kimliğini) ve bot tercihlerini saklar. Onaylanmayan kayıtlar 7 gün, gönderilmiş mail kayıtları 30 gün sonra otomatik silinir; abonelikten çıkan herkesin adresi hemen silinir. Ayrıntılar sitedeki **/gizlilik** sayfasında. Site ücretli hale gelirse ya da kapsamı büyürse SPK (yatırım danışmanlığı) ve KVKK yükümlülükleri için bir hukukçuya danış.

## Sorun giderme

- **Site açılmıyor / sertifika hatası:** `docker compose logs caddy`. DNS kaydı sunucu IP'sini göstermeli ve 80/443 açık olmalı (`ufw status`). Sertifika ilk açılışta birkaç saniye sürer.
- **Onay maili gelmiyor:** önce spam klasörü. Sonra `docker compose logs engine | grep -i sending` ve yukarıdaki "gönderilemeyen mailler" sorgusu. Gmail'de `Username and Password not accepted` hatası = uygulama şifresi yanlış ya da 2 adımlı doğrulama kapalı.
- **"Motor durdu" görünüyor:** `docker compose logs --tail 100 engine`. Binance'e erişim sorunu olabilir; motor ağ hatalarında kendisi tekrar dener.
- **Telegram botu cevap vermiyor:** loglarda `Telegram` ara; token doğru mu? Aynı token'la başka bir yerde çalışan bot varsa (eski VPS gibi) onu kapat.
