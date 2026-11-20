# Botu ve siteyi bu bilgisayarda başlatır ve Cloudflare Tunnel ile internete açar.
#   Çift tıkla: scripts\windows\baslat.bat      Durdurmak: bu pencerede Ctrl+C
#
# - Ücretsiz "quick tunnel" her başlatmada YENİ bir https://xxxx.trycloudflare.com adresi verir.
# - Pencere açık kaldığı sürece bilgisayar uykuya geçmez (ayarlarına dokunulmaz).
param([int]$Port = 8000)
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { Write-Host "Önce kurulumu çalıştır: scripts\windows\kurulum.bat" -ForegroundColor Red; exit 1 }
if (-not (Test-Path "cryptobot\web\dist\index.html")) { Write-Host "Arayüz derlenmemiş: scripts\windows\kurulum.bat" -ForegroundColor Red; exit 1 }
if (-not (Test-Path ".env")) { Write-Host ".env yok: scripts\windows\kurulum.bat" -ForegroundColor Red; exit 1 }
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Write-Host "cloudflared yok. Kur: winget install --id Cloudflare.cloudflared" -ForegroundColor Red; exit 1
}

# bilgisayar bu pencere açıkken uyumasın (ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
Add-Type -Namespace Win32 -Name Power -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);'
[void][Win32.Power]::SetThreadExecutionState([uint32]"0x80000001")

# önceki çalıştırmadan kalanları kapat (pencere X ile kapatıldıysa tünel ve bot arka planda kalabiliyor).
# Sadece BU klasörün tüneli ve botu kapatılır; iki bot aynı anda çalışırsa Telegram'da çakışırlar.
$LogDir = Join-Path $Root "data\logs"
$PyDir = Join-Path $Root ".venv"
$old = Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe' OR Name='python.exe'" | Where-Object {
    $_.CommandLine -and (
        ($_.Name -eq "cloudflared.exe" -and $_.CommandLine.Contains($LogDir)) -or
        ($_.Name -eq "python.exe" -and $_.CommandLine -match "cryptobot" -and $_.ExecutablePath -and $_.ExecutablePath.StartsWith($PyDir))
    )
}
foreach ($p in $old) {
    Write-Host "Önceki çalıştırmadan kalan $($p.Name) (PID $($p.ProcessId)) kapatılıyor." -ForegroundColor Yellow
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
if ($old) { Start-Sleep -Seconds 2 }

# port doluysa (başka bir program kullanıyorsa) sıradaki boş portu seç
function Test-PortFree([int]$p) {
    try {
        $l = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $p)
        $l.Start(); $l.Stop(); return $true
    } catch { return $false }
}
$wanted = $Port
while (-not (Test-PortFree $Port)) {
    $Port++
    if ($Port -gt $wanted + 20) { Write-Host "$wanted-$Port arasında boş port yok." -ForegroundColor Red; exit 1 }
}
if ($Port -ne $wanted) { Write-Host "Port $wanted dolu, $Port kullanılıyor." -ForegroundColor Yellow }

New-Item -ItemType Directory -Force -Path data\logs | Out-Null
$TunnelLog = Join-Path $Root "data\logs\tunnel.log"
if (Test-Path $TunnelLog) { Remove-Item $TunnelLog -Force -ErrorAction SilentlyContinue }

Write-Host "==> Cloudflare tüneli açılıyor..." -ForegroundColor Cyan
$tunnel = Start-Process cloudflared -ArgumentList @("tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:$Port", "--logfile", $TunnelLog) `
    -WindowStyle Hidden -PassThru

$url = $null
for ($i = 0; $i -lt 60 -and -not $url; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Path $TunnelLog) {
        $m = Select-String -Path $TunnelLog -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" | Select-Object -First 1
        if ($m) { $url = $m.Matches[0].Value }
    }
}
if (-not $url) {
    Write-Host "Tünel adresi alınamadı. Ayrıntı: $TunnelLog" -ForegroundColor Red
    Stop-Process -Id $tunnel.Id -ErrorAction SilentlyContinue
    exit 1
}

$env:PUBLIC_URL = $url          # Telegram mesajlarındaki linkler bu adresi kullanır
try { Set-Clipboard -Value $url } catch {}

Write-Host ""
Write-Host "  Site adresi (panoya kopyalandı):" -ForegroundColor Green
Write-Host "  $url" -ForegroundColor Green
Write-Host ""
Write-Host "  Bu pencereyi KAPATMA. Durdurmak için Ctrl+C." -ForegroundColor Yellow
Write-Host "  Not: adres her başlatmada değişir; arkadaşlarına yenisini gönder." -ForegroundColor Yellow
Write-Host ""

try {
    & $Python -m cryptobot all --port $Port
} finally {
    Write-Host "==> Kapatılıyor..." -ForegroundColor Cyan
    Stop-Process -Id $tunnel.Id -ErrorAction SilentlyContinue
    [void][Win32.Power]::SetThreadExecutionState([uint32]"0x80000000")
}
