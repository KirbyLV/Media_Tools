#!/usr/bin/env python3
"""
Download static ffmpeg + ffprobe builds that include the HAP encoder into
AudioExtractor/bin, then prove they work with a real HAP encode.

  macOS arm64  : Martin Riedl's build server (native), fallback evermeet.cx (Intel/Rosetta)
  macOS x86_64 : evermeet.cx, fallback Martin Riedl amd64
  Windows x64  : gyan.dev "full" shared build (the only gyan variant with libsnappy)

Usage: python scripts/fetch_ffmpeg.py [--force]
"""
from __future__ import annotations

import argparse
import io
import json
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"
UA = {"User-Agent": "AudioExtractor-build/1.0"}
IS_WIN = sys.platform.startswith("win")
EXE = ".exe" if IS_WIN else ""


def get(url: str) -> bytes:
    print(f"  GET {url}")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=600) as r:
        return r.read()


def unzip_one(data: bytes, name: str, dest: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for m in z.namelist():
            if Path(m).name == name and not m.endswith("/"):
                dest.write_bytes(z.read(m))
                dest.chmod(0o755)
                return
    raise RuntimeError(f"{name} not found in archive")


# --- sources ---------------------------------------------------------------
def riedl(arch: str):
    def fetch():
        for tool in ("ffmpeg", "ffprobe"):
            data = get(f"https://ffmpeg.martin-riedl.de/redirect/latest/macos/{arch}/release/{tool}.zip")
            unzip_one(data, tool, BIN / tool)
        return f"Martin Riedl FFmpeg Build Server (macos/{arch}) - https://ffmpeg.martin-riedl.de"
    return fetch


def evermeet():
    for tool in ("ffmpeg", "ffprobe"):
        info = json.loads(get(f"https://evermeet.cx/ffmpeg/info/{tool}/release"))
        url = (((info.get("download") or {}).get("zip") or {}).get("url")
               or f"https://evermeet.cx/ffmpeg/{tool}-{info['version']}.zip")
        unzip_one(get(url), tool, BIN / tool)
    return "evermeet.cx static build (macOS x86_64) - https://evermeet.cx/ffmpeg/"


def gyan_full_shared():
    sz = shutil.which("7z") or shutil.which("7za") or r"C:\Program Files\7-Zip\7z.exe"
    if not Path(sz).exists() and not shutil.which(sz):
        raise RuntimeError("7-Zip is required to unpack the gyan.dev .7z build")
    with tempfile.TemporaryDirectory() as td:
        arc = Path(td) / "ffmpeg.7z"
        arc.write_bytes(get("https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-full-shared.7z"))
        subprocess.run([sz, "x", "-y", f"-o{td}", str(arc)], check=True, stdout=subprocess.DEVNULL)
        bindir = next(Path(td).glob("*/bin"))
        for f in bindir.iterdir():
            if f.suffix.lower() in (".dll",) or f.name in ("ffmpeg.exe", "ffprobe.exe"):
                shutil.copy2(f, BIN / f.name)
        lic = next(Path(td).glob("*/LICENSE*"), None)
        if lic:
            shutil.copy2(lic, BIN / "FFMPEG_LICENSE.txt")
    return "gyan.dev release full (shared) build - https://www.gyan.dev/ffmpeg/builds/"


def sources():
    if IS_WIN:
        return [gyan_full_shared]
    if sys.platform == "darwin":
        if platform.machine() == "arm64":
            return [riedl("arm64"), evermeet]
        return [evermeet, riedl("amd64")]
    raise SystemExit("Bundled builds are set up for macOS and Windows only.")


# --- verification ------------------------------------------------------------
def verify() -> str:
    ff, fp = BIN / f"ffmpeg{EXE}", BIN / f"ffprobe{EXE}"
    enc = subprocess.run([str(ff), "-hide_banner", "-encoders"], capture_output=True, text=True, check=True).stdout
    if " hap " not in enc:
        raise RuntimeError("this ffmpeg has no HAP encoder")
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "t.mov"
        subprocess.run([str(ff), "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=16x16:r=30000/1001:d=1",
                        "-f", "lavfi", "-i", "sine=f=440:d=1", "-map", "0:v", "-map", "1:a",
                        "-c:v", "hap", "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(out)], check=True)
        probe = subprocess.run([str(fp), "-v", "error", "-show_entries", "stream=codec_name",
                                "-of", "csv=p=0", str(out)], capture_output=True, text=True, check=True).stdout.split()
        if probe != ["hap", "pcm_s16le"]:
            raise RuntimeError(f"test encode produced {probe}")
    return subprocess.run([str(ff), "-version"], capture_output=True, text=True).stdout


def main():
    # Windows consoles default to cp1252; never crash on printing a character.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="re-download even if bin/ is already valid")
    args = ap.parse_args()
    BIN.mkdir(exist_ok=True)

    if not args.force and (BIN / f"ffmpeg{EXE}").exists():
        try:
            verify()
            print("bin/ already has a working HAP-capable ffmpeg.")
            return
        except Exception as e:
            print(f"Existing bin/ ffmpeg unusable ({e}); re-downloading.")

    errors = []
    for src in sources():
        for f in BIN.iterdir():
            f.unlink() if f.is_file() else shutil.rmtree(f)
        try:
            origin = src()
            version = verify()
        except Exception as e:
            errors.append(f"{getattr(src, '__name__', src)}: {e}")
            print(f"  [FAIL] {errors[-1]}")
            continue
        (BIN / "FFMPEG_BUILD.txt").write_text(
            f"Source: {origin}\nFFmpeg source code: https://ffmpeg.org/download.html\n\n{version}", encoding="utf-8")
        print(f"[OK] HAP-capable ffmpeg ready in {BIN}\n  {version.splitlines()[0]}\n  from {origin}")
        return
    raise SystemExit("No working ffmpeg build found:\n  " + "\n  ".join(errors))


if __name__ == "__main__":
    main()
