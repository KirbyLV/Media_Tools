"""
Audio Extractor core — no GUI dependencies.

Wraps an audio file (or the audio track of a video) in a MOV containing a
16x16 black HAP video stream + 48 kHz stereo PCM16LE audio, at a chosen
frame rate. Ported from FileReporter2/media_utils.ffmpeg_extract_audio.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

AUDIO_EXTS = {'.wav', '.aiff', '.aif', '.mp3', '.m4a', '.flac', '.ogg', '.aac',
              '.opus', '.wma', '.oga', '.ac3', '.dts', '.alac', '.ape', '.mka'}
VIDEO_EXTS = {'.mp4', '.mov', '.mxf', '.mkv', '.avi', '.m4v', '.webm', '.wmv',
              '.mpg', '.mpeg', '.ts', '.m2ts', '.mts', '.3gp', '.flv', '.vob',
              '.ogv', '.dv', '.asf', '.qt'}
SUPPORTED_EXTS = AUDIO_EXTS | VIDEO_EXTS


@dataclass(frozen=True)
class FrameRate:
    label: str          # shown in dropdown and used in filename
    rate: str | None    # ffmpeg rational, e.g. "30000/1001"; None = match source


MATCH_SOURCE = FrameRate("Match source", None)
FRAME_RATES = [
    MATCH_SOURCE,
    FrameRate("23.976", "24000/1001"),
    FrameRate("24", "24"),
    FrameRate("25", "25"),
    FrameRate("29.97", "30000/1001"),
    FrameRate("30", "30"),
    FrameRate("47.952", "48000/1001"),
    FrameRate("48", "48"),
    FrameRate("50", "50"),
    FrameRate("59.94", "60000/1001"),
    FrameRate("60", "60"),
    FrameRate("119.88", "120000/1001"),
    FrameRate("120", "120"),
]
FALLBACK_FPS = FrameRate("30", "30")


# --- ffmpeg discovery --------------------------------------------------------
_BUNDLE_BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
_tool_cache: dict[str, str] = {}


def _find_tool(name: str) -> str:
    """Find ffmpeg/ffprobe: bundled inside the app first, then PATH, then
    common installs (apps launched from Finder don't inherit Homebrew's PATH)."""
    if name in _tool_cache:
        return _tool_cache[name]
    exe = name + (".exe" if os.name == "nt" else "")
    candidates = [_BUNDLE_BASE / "bin" / exe, _BUNDLE_BASE / exe]
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / exe)
    found = shutil.which(name)
    if found:
        candidates.append(Path(found))
    candidates += [Path("/opt/homebrew/bin") / exe, Path("/usr/local/bin") / exe,
                   Path("/usr/bin") / exe, Path(r"C:\ffmpeg\bin") / exe]
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            if sys.platform == "darwin" and is_bundled(str(c)):
                # Unzipped downloads carry Gatekeeper quarantine on every file;
                # clear it on our own bundled tools so they can be launched.
                subprocess.run(["xattr", "-d", "com.apple.quarantine", str(c)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _tool_cache[name] = str(c)
            return str(c)
    raise FileNotFoundError(
        f"{name} not found. Install ffmpeg (e.g. `brew install ffmpeg`) "
        f"or place {exe} in a 'bin' folder next to the app.")


def is_bundled(path: str) -> bool:
    try:
        return Path(path).resolve().is_relative_to(_BUNDLE_BASE.resolve())
    except Exception:
        return False


def _exec(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    """subprocess.run with a readable error for an Intel ffmpeg on a Mac without Rosetta."""
    try:
        return subprocess.run(cmd, **kw, **_run_kwargs())
    except OSError as e:
        if getattr(e, "errno", None) == 86:  # Bad CPU type in executable
            raise RuntimeError("This ffmpeg is Intel-only. Install Rosetta: "
                               "softwareupdate --install-rosetta --agree-to-license") from e
        raise


def _run_kwargs() -> dict:
    """Hide console windows on Windows builds."""
    if os.name != "nt":
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {"startupinfo": si, "creationflags": subprocess.CREATE_NO_WINDOW}


def check_ffmpeg() -> str:
    """Return a short status string, or raise if ffmpeg/ffprobe/HAP are unavailable."""
    ffmpeg = _find_tool("ffmpeg")
    _find_tool("ffprobe")
    enc = _exec([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    if " hap " not in enc:
        raise RuntimeError("This ffmpeg build has no HAP encoder (needs libsnappy).")
    ver = _exec([ffmpeg, "-version"], capture_output=True, text=True).stdout.split()
    version = ver[2] if len(ver) > 2 else "?"
    return f"ffmpeg {version} · {'bundled' if is_bundled(ffmpeg) else ffmpeg}"


# --- probing -----------------------------------------------------------------
def _ffprobe_json(args: list[str]) -> dict:
    proc = _exec([_find_tool("ffprobe"), "-v", "error", *args, "-of", "json"],
                 capture_output=True, check=True)
    return json.loads(proc.stdout.decode("utf-8", errors="ignore"))


def probe_fps(src: str) -> str | None:
    """Source video avg frame rate as an ffmpeg rational string, or None."""
    try:
        s = _ffprobe_json(["-select_streams", "v:0",
                           "-show_entries", "stream=avg_frame_rate,codec_type", src]).get("streams") or []
        afr = s[0].get("avg_frame_rate") if s else None
        if afr and afr != "0/0":
            num, den = afr.split("/")
            if float(den) and float(num):
                return afr
    except Exception:
        pass
    return None


def probe_audio_duration(src: str) -> float | None:
    """Duration of first audio stream, falling back to container duration."""
    for args, pick in (
        (["-select_streams", "a:0", "-show_entries", "stream=duration"],
         lambda d: (d.get("streams") or [{}])[0].get("duration")),
        (["-show_entries", "format=duration"],
         lambda d: (d.get("format") or {}).get("duration")),
    ):
        try:
            v = pick(_ffprobe_json([*args, src]))
            if v not in (None, "N/A"):
                return float(v)
        except Exception:
            pass
    return None


def has_audio(src: str) -> bool:
    try:
        return bool(_ffprobe_json(["-select_streams", "a",
                                   "-show_entries", "stream=index", src]).get("streams"))
    except Exception:
        return False


def fps_label(rate: str) -> str:
    """'30000/1001' -> '29.97', '24' -> '24'."""
    for fr in FRAME_RATES:
        if fr.rate == rate:
            return fr.label
    try:
        num, _, den = rate.partition("/")
        v = float(num) / float(den or 1)
        return f"{v:.3f}".rstrip("0").rstrip(".")
    except Exception:
        return rate


# --- main operation ----------------------------------------------------------
def extract_audio(src: str, frame_rate: FrameRate = MATCH_SOURCE,
                  out_dir: str | None = None, overwrite: bool = True) -> str:
    """
    Create <stem>_hapaudio.mov: 16x16 black HAP + 48k stereo PCM16LE.
    Returns the output path. Raises RuntimeError on failure.
    """
    p = Path(src)
    if not p.is_file():
        raise RuntimeError(f"File not found: {src}")
    if not has_audio(src):
        raise RuntimeError("No audio stream found")

    rate = frame_rate.rate or probe_fps(src) or FALLBACK_FPS.rate

    target_dir = Path(out_dir) if out_dir else p.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / f"{p.stem}_hapaudio.mov"

    dur = probe_audio_duration(src)
    color = f"color=c=black:s=16x16:r={rate}"
    if dur and dur > 0:
        color += f":d={dur:.6f}"

    cmd = [_find_tool("ffmpeg"), "-hide_banner", "-nostdin",
           "-y" if overwrite else "-n",
           "-f", "lavfi", "-i", color,
           "-i", str(p),
           "-map", "0:v:0", "-map", "1:a:0",
           "-c:v", "hap", "-tune", "stillimage",
           "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2",
           "-r", rate,
           "-f", "mov"]
    if not dur:
        cmd.append("-shortest")
    cmd.append(str(out_path))

    proc = _exec(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-6:])
        raise RuntimeError(f"ffmpeg failed:\n{tail}")
    return str(out_path)


if __name__ == "__main__":
    # CLI: python extractor.py <fps|match> file1 [file2 ...]
    if len(sys.argv) < 3:
        print("usage: extractor.py <fps label|match> <files...>")
        print("fps labels:", ", ".join(f.label for f in FRAME_RATES[1:]))
        sys.exit(1)
    choice = sys.argv[1]
    fr = MATCH_SOURCE if choice.lower() == "match" else next(
        (f for f in FRAME_RATES if f.label == choice), FrameRate(choice, choice))
    for f in sys.argv[2:]:
        try:
            print("OK  ", extract_audio(f, fr))
        except Exception as e:
            print("FAIL", f, "-", e)
