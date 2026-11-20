# Bir kerelik kurulum (Windows): Python ortamı, paketler, arayüz derlemesi, .env
#   Çift tıkla: scripts\windows\kurulum.bat
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root

function Adim($t) { Write-Host ""; Write-Host "==> $t" -ForegroundColor Cyan }
function Hata($t) { Write-Host ""; Write-Host "HATA: $t" -ForegroundColor Red; exit 1 }

if ($Root.Path.Length -gt 120) {
    Hata "Klasör yolu çok uzun ($($Root.Path.Length) karakter). Windows'ta paketler kurulamıyor; projeyi C:\kripto-sinyal gibi kısa bir yola taşı."
}

Adim "Python ortamı (.venv)"
if (Get-Command uv -ErrorAction SilentlyContinue) {
    uv venv --python 3.12 .venv
    if (-not $?) { Hata "uv venv başarısız" }
    uv pip install --python .venv\Scripts\python.exe -r requirements.txt
    if (-not $?) { Hata "paket kurulumu başarısız" }
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    python -m venv .venv
    if (-not $?) { Hata "python -m venv başarısız" }
    .venv\Scripts\python.exe -m pip install -r requirements.txt
    if (-not $?) { Hata "paket kurulumu başarısız" }
} else {
    Hata "Python bulunamadı. https://www.python.org/downloads/ adresinden Python 3.12 kur (kurarken 'Add to PATH' kutusunu işaretle)."
}

Adim "Arayüz (React) derleniyor"
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Hata "Node.js bulunamadı. https://nodejs.org adresinden LTS sürümünü kur."
}
Push-Location frontend
npm ci --no-audit --no-fund
if (-not $?) { Pop-Location; Hata "npm ci başarısız" }
npm run build
if (-not $?) { Pop-Location; Hata "arayüz derlenemedi" }
Pop-Location

Adim ".env dosyası"
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host "    .env oluşturuldu. Telegram bilgilerini yazmak için: notepad .env"
} else {
    Write-Host "    .env zaten var, dokunulmadı."
}

Adim "Cloudflare Tunnel (cloudflared)"
if (Get-Command cloudflared -ErrorAction SilentlyContinue) {
    Write-Host "    cloudflared kurulu: $((cloudflared --version) 2>&1)"
} else {
    Write-Host "    cloudflared kurulu değil. Bir terminalde şunu çalıştır, sonra bu pencereyi kapatıp yenisini aç:" -ForegroundColor Yellow
    Write-Host "      winget install --id Cloudflare.cloudflared" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Kurulum tamam. Başlatmak için: scripts\windows\baslat.bat" -ForegroundColor Green
