#!/usr/bin/env bash
# Build "Audio Extractor.app" with ffmpeg bundled, zipped for sharing.
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
VERSION="$(cat VERSION 2>/dev/null || echo 1.0.0)"
ARCH="$(uname -m)"

"$PY" -m pip install -q -r requirements.txt pyinstaller
"$PY" scripts/fetch_ffmpeg.py

rm -rf build dist
"$PY" -m PyInstaller --noconfirm --clean --windowed \
  --name "Audio Extractor" \
  --osx-bundle-identifier com.jspodick.audioextractor \
  --collect-all customtkinter --collect-all tkinterdnd2 \
  --add-binary "bin/ffmpeg:bin" --add-binary "bin/ffprobe:bin" \
  --add-data "bin/FFMPEG_BUILD.txt:." --add-data "THIRD_PARTY_NOTICES.md:." \
  audio_extractor.py

APP="dist/Audio Extractor.app"
# Smoke test: the ffmpeg inside the bundle must have HAP
FF="$(find "$APP" -type f -name ffmpeg | head -1)"
"$FF" -hide_banner -encoders | grep -q " hap " || { echo "Bundled ffmpeg lacks HAP"; exit 1; }

ZIP="dist/AudioExtractor-${VERSION}-macOS-${ARCH}.zip"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"
echo "Built: $ZIP"
