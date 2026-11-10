# Audio Extractor

Standalone version of FileReporter2's "extract audio". Takes WAV/audio files,
or the audio track of a video, and writes `<source>_hapaudio.mov` containing:

- 16×16 black **HAP** video at the frame rate you pick
- **48 kHz stereo PCM 16-bit** audio (mono sources are upmixed to stereo)

Frame-rate dropdown: Match source, 23.976, 24, 25, 29.97, 30, 47.952, 48, 50,
59.94, 60, 119.88, 120. NTSC rates use exact rationals (30000/1001 etc.).
"Match source" uses the video's rate and falls back to 30 for audio-only files.

## For users
Download the zip for your machine from the repo's **Releases** page, unzip,
run. ffmpeg is bundled — nothing else to install.

- **Mac first launch:** the app isn't notarized, so macOS blocks it once.
  System Settings → Privacy & Security → **Open Anyway**.
- **Windows:** on a SmartScreen warning, click **More info → Run anyway**.

## Publishing a release
```
git tag audio-extractor-v1.0.0
git push origin audio-extractor-v1.0.0
```
The `audio-extractor` GitHub Action builds Apple Silicon, Intel Mac and
Windows apps, checks that each bundled ffmpeg can actually encode HAP, and
attaches the zips to a GitHub Release. Run it manually from the Actions tab to
get test builds without publishing.

## Building locally
- macOS: `./build.sh` → `dist/AudioExtractor-<ver>-macOS-<arch>.zip`
- Windows: `./build.ps1` (needs 7-Zip) → `dist/AudioExtractor-<ver>-Windows-x64.zip`

Both run `scripts/fetch_ffmpeg.py`, which downloads a static ffmpeg + ffprobe
into `bin/` and test-encodes a HAP file before anything gets packaged.

## Running from source
```
pip install -r requirements.txt
python audio_extractor.py
```
Uses `bin/ffmpeg` if present, otherwise your installed ffmpeg (needs HAP:
`ffmpeg -encoders | grep hap`).

## CLI
```
python extractor.py 29.97 file1.wav clip.mov
python extractor.py match *.mp4
```
