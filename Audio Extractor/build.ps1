# Build "Audio Extractor" for Windows with ffmpeg bundled, zipped for sharing.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Version = if (Test-Path VERSION) { (Get-Content VERSION).Trim() } else { "1.0.0" }

python -m pip install -q -r requirements.txt pyinstaller
python scripts/fetch_ffmpeg.py
if ($LASTEXITCODE -ne 0) { throw "ffmpeg fetch failed" }

Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
python -m PyInstaller --noconfirm --clean --windowed `
  --name "Audio Extractor" `
  --collect-all customtkinter --collect-all tkinterdnd2 `
  --add-data "bin;bin" --add-data "THIRD_PARTY_NOTICES.md;." `
  audio_extractor.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$ff = Get-ChildItem -Recurse "dist/Audio Extractor" -Filter ffmpeg.exe | Select-Object -First 1
if (-not ((& $ff.FullName -hide_banner -encoders) -match " hap ")) { throw "Bundled ffmpeg lacks HAP" }

$zip = "dist/AudioExtractor-$Version-Windows-x64.zip"
Compress-Archive -Path "dist/Audio Extractor" -DestinationPath $zip -Force
Write-Host "Built: $zip"
