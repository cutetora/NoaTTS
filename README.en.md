<div align="left">
  <img src="https://count.getloli.com/get/@cutetora-noatts?theme=moebooru" alt="visitors" height="32">
</div>

[日本語](README.md) | **English** | [中文](README.zh.md)

# NoaTTS

**A local Japanese TTS that lets your characters speak in the voice you choose.** Type some text, and it reads it aloud in the voice you created.
**No internet required — everything runs entirely on your own PC** (Windows / NVIDIA GPU required).
The tricky settings? The mascot "Noa" walks you through them right on screen.

<p align="center"><img src="assets/mascot.png" alt="Mascot Noa" height="150"></p>

## What it can do

### 🎨 Create the voice you want (3 ways)
| Method | Who it's for | Ease |
|---|---|---|
| **Voice cloning** | You want to reproduce a voice from **3–10 seconds of audio** you already have | ★★ |
| **Custom voice** | You want to pick a ready-made voice and fine-tune it (Qwen3) | ★★★ easy |
| **Voice Design** | You want to craft the voice qualities in fine detail | ★ |

> Voices you create are saved as "voice cards" and can be switched anytime.
> (See the [License](#license) for notes on commercial use and cloning.)
>
> 🛠 Features that help you create: even if the reference audio has BGM, **BGM removal (Demucs)** extracts the vocals / before saving, you can pick a good voice via a **5-seed comparison** and **audition it with joy/anger/sorrow/fun** to check how the emotion rides.

### 🥺 Add emotion
Drop emojis like **😭😠🥺** into your text, and **the emotion comes through while the voice stays the same** (Irodori).
Crying, anger, a stifled chuckle, whispering, fast talking, and more. Give your characters' lines real expression.

### 📄 Turn a whole script into audio (batch line generation)
Load a **CSV/Excel script**, assign a voice to each character, and **generate everything at once**.
Great for producing material for videos, games, voice dramas, and audio readings. No more exporting lines one at a time.

### 🔔 Make your voice a resident "read-aloud assistant"
It stays resident in the system tray and reads aloud the moment you send it text. Handy for things like task-completion notifications.
Other apps and scripts can call it too (**[OpenAI TTS API compatible](#http-api)** · fully local / no API key required · for advanced users).

<!-- TODO(screenshots): Place images under assets/screenshots/ and insert them into each section
     like ![](assets/screenshots/voice-studio.png).
     Recommended: voice-studio.png / batch-generate.png / tts-settings.png -->

### 🔊 Audio samples (click to play / download)

| Sample | Description |
|---|---|
| 🎀 **Female · standard** | [Noa's voice](assets/screenshots/samples/01_standard_noa.mp3?raw=1) — a bright, cheerful support character |
| 🧭 **Male · standard** | ["man" voice](assets/screenshots/samples/01_standard_male_man.mp3?raw=1) — a lively, sardonic adventurer type |
| 😊 **Emotion (same voice)** | [stifled chuckle](assets/screenshots/samples/02_emotion_warai.mp3?raw=1) · [anger](assets/screenshots/samples/03_emotion_okori.mp3?raw=1) · [crying](assets/screenshots/samples/04_emotion_naki.mp3?raw=1) · [trembling voice](assets/screenshots/samples/05_emotion_furue.mp3?raw=1) |
| 🎭 **Voice cloning** | [original voice (Before)](assets/screenshots/samples/clone_before_tsukuyomi.mp3?raw=1) → [cloned voice (After)](assets/screenshots/samples/clone_after_1.mp3?raw=1) |

> 📌 The reference audio for cloning uses "Tsukuyomi-chan's sample voice" (included for the purpose of introducing the software).
> 　Material used: Tsukuyomi-chan's sample voice <https://tyc.rei-yumesaki.net/material/voice/sample-voice/>

---

## Technical highlights

- **Two switchable TTS engines** — [Qwen3-TTS](https://huggingface.co/Qwen) / [Irodori-TTS](https://huggingface.co/Aratako) (never loaded at the same time)
- **VRAM-resident daemon** — after the initial load, it reads aloud with no wait (about 1.3GB at idle)
- **⚡Lightweight mode** — an int4 lightweight model saves VRAM (about 1.5GB even while speaking). Easier to run alongside heavy apps like image generation or games
- **Three input paths** — HTTP API / file watching / Windows named pipe

---

## System requirements

> Windows recommended (the development and testing environment). The named pipe path is Windows-only, but **the HTTP API / file-watching paths are designed to work on Mac / Linux too** (since v1.1.0 · untested on Mac/Linux). An NVIDIA GPU with CUDA is assumed for the GPU (CPU-only operation is not practical).

**Minimum spec** (just reading aloud in ⚡Lightweight mode)
→ Windows 10/11 (64-bit) / NVIDIA GPU with **4GB VRAM** (about 2.0GB in actual use) / 8GB RAM / 10GB free SSD space / Python 3.11 + CUDA-enabled PyTorch

**Recommended spec** (comfortable voice creation; also using the large Qwen3 and Voice Design)
→ Windows 11 / NVIDIA RTX-series GPU with **8GB+ VRAM** (12GB+ if you use the large Qwen3 1.7B) / 16GB+ RAM / 20GB+ free SSD space

See the table below and the VRAM notes underneath it for details.

| Item | Minimum | Recommended |
|---|---|---|
| OS | Windows 10 / 11 (64-bit) | Windows 11 (64-bit) |
| GPU | NVIDIA (CUDA-enabled) / 4GB+ VRAM (in ⚡Lightweight mode) | NVIDIA RTX series / 8GB+ VRAM (12GB+ if using the large Qwen3 1.7B) |
| Mainly usable engine | Mostly Irodori 500M | Qwen3 1.7B and Voice Design switch comfortably too |
| Memory (RAM) | 8GB | 16GB+ |
| Storage | 10GB+ free SSD | 20GB+ free SSD |
| Python | 3.11 | 3.11 |
| PyTorch | CUDA-enabled build | CUDA 12.x build (verified: torch 2.11.0+cu128 / CUDA 12.8) |

> ⚠️ **Measured VRAM** (including CUDA context) — varies by use case.
>
> | Usage | VRAM |
> |---|---|
> | Reading aloud only + ⚡Lightweight mode (int4) | **about 2.0GB** (comfortable even on a 4GB GPU) |
> | Reading aloud only + standard model (Irodori 500M) | about 3GB |
> | + Voice Studio (voice creation) running in parallel | + about 2GB (automatically offloaded when idle) |
> | Qwen3-TTS 1.7B (large engine) | 6–8GB |
>
> The engines (Qwen3 / Irodori) are **never loaded at the same time** (their requirements don't add up).
> `setup.bat` auto-detects CUDA and installs the matching PyTorch.

---

## Getting it

There are two ways, depending on how you want to use it. **If you just want to use it normally, the "portable version" is by far the easiest.**

### A. Portable version (recommended · no Python or CUDA needed)

[**Download the latest release**](https://github.com/cutetora/NoaTTS/releases/latest) → grab it from **Assets** and use it.

| Format | Steps | Best for |
|---|---|---|
| **Installer** `NoaTTS-Setup.exe` | Double-click to install → launch from `NoaTTS` on your desktop | The most common choice |
| **ZIP** `NoaTTS-portable-THIN.zip` | Extract → double-click `NoaTTS.exe` | People who prefer to extract and run |

- **Only on the first launch**, it **automatically downloads** the PyTorch matching your GPU (CUDA auto-detected) and the TTS models (several GB, a few minutes, internet required). It launches instantly from the second time on.
- **All you need is an NVIDIA GPU and the latest driver.** You don't have to install Python or the CUDA Toolkit yourself.
- Once initial setup finishes, **Voice Studio (the voice creation UI) opens automatically** as a stand-in tutorial.

> Only if you want to use Lightweight mode (int4), run `python\python.exe -m pip install -r requirements-lite.txt` inside the distribution (optional · Windows).

### B. From source (for developers · provide git + Python yourself)

- **ZIP**: Get the latest main from the green "Code" → "Download ZIP".
- **git clone**:
  ```bash
  git clone https://github.com/cutetora/NoaTTS.git
  ```

> For this route, follow the "Setup" section below and install Python 3.11 / PyTorch yourself. `setup.bat` (in a winget environment) can also auto-install git / Python.

---

## Setup (when using from source)

> 💡 **If you want one-click usage, use "A. Portable version" above** (`NoaTTS-Setup.exe` / ZIP). No Python or CUDA needed.
>
> The following is the **developer procedure for running from source**. It **assumes you install Python 3.11 and CUDA-enabled PyTorch yourself** (because PyTorch depends on your environment's CUDA version, the portable version installs it automatically on first launch).

### Easy: `setup.bat` (for CUDA 12.8 / winget environments)

**Double-click `setup.bat`** and it automatically does the following:

1. Installs `git` / `Python 3.11` via winget (if missing)
2. Creates a `venv` (virtual environment)
3. Installs the CUDA 12.8 build of PyTorch
4. Installs the dependencies from `requirements.txt`
5. **Pre-downloads the TTS models** (several GB, a few minutes — downloaded here so the first launch is fast)

> ⚠️ `setup.bat` **automatically checks for an NVIDIA GPU and auto-detects the GPU's CUDA version** to install the matching PyTorch (auto-selects cu128 / cu124 / cu121 / cu118). If winget is available, it also auto-installs git / Python. In environments without winget, install git / Python manually before running it.

When it's done, launch with `run_tray.bat` (or `NoaTTS.exe`). If a `venv` exists, each bat / exe uses it automatically. The models are already fetched during setup, so you can use it immediately after launch.

### Manual setup

Python 3.11 is recommended. **Install PyTorch first**, then install the dependencies.

1. Install **Python 3.11** (so it can be invoked with `py -3.11`).
2. Install **CUDA-enabled PyTorch** (matching your environment's CUDA version).
   Install `torch` and `torchaudio` from <https://pytorch.org/get-started/locally/>
   (verified: torch 2.11.0+cu128 / CUDA 12.8).
3. Install the remaining dependencies (**git is required** because the TTS engines are fetched from GitHub).

```bash
pip install -r requirements.txt
```

4. (Optional) Pre-downloading the models makes the first launch faster. If you skip this, they're fetched automatically on first launch.

```bash
python download_models.py
```

---

## How to launch

There are four ways, depending on your goal. For everyday use, **double-clicking `NoaTTS.exe`** is the easiest.

| What you want to do | How to launch | Description |
|---|---|---|
| Everyday use (recommended) | **Double-click `NoaTTS.exe`** | A launcher with an icon that starts the tray-resident app without showing a black console window (internally the same tray launch as `run_tray.bat`) |
| Tray-resident (bat version) | `run_tray.bat` | Tray icon + Web UI + daemon management, all together |
| Just read-aloud | `python noa_tts_daemon.py` | The daemon alone. Starts the HTTP API (:7870), file watching, and pipe |
| Voice creation Web UI alone | `run.bat` | The Gradio Voice Studio (:7860) |

After it's tray-resident:

- **Double-click the tray icon** → opens Voice Studio (the Web UI)
- **Right-click the tray icon** → a menu for read-aloud settings, voice selection, model offloading, and more

Specify the daemon's voice with `--voice <name>` (default is `noa`). The only bundled voice is `noa`; you create other voices yourself from the Web UI.

```bash
python noa_tts_daemon.py --voice noa
```

> `NoaTTS.exe` is `noa_launcher.py` built with PyInstaller. To rebuild it yourself:
> ```bash
> py -3.11 -m PyInstaller --onefile --noconsole --icon assets/noa.ico --name NoaTTS noa_launcher.py
> ```

---

## HTTP API

> 🧩 **For developers:** **OpenAI TTS API compatible** (`/v1/audio/speech`). You can use it by **just swapping the base URL** of an existing OpenAI-TTS client. **Fully local · no API key required · no metered billing · your audio is never sent anywhere.**

While the daemon is running, opening `http://127.0.0.1:7870/` in a browser brings up a control panel.

| Method | Path | Description |
|---|---|---|
| `POST` | `/say` | Reads aloud the body (plain or JSON). Always reads even when the toggle is OFF |
| `POST` | `/say_wav` | Returns the synthesized WAV (does not play it). For when you want to play it on the client side |
| `POST` | `/v1/audio/speech` | **OpenAI TTS API compatible.** Usable as a drop-in replacement from an existing OpenAI-TTS client |
| `POST` | `/stop` | Interrupts the read-aloud |
| `POST` | `/voice` | Switches voice (`{"name": "..."}`) |
| `POST` | `/speed` | Changes speech speed (`{"speed": 1.0}`) |
| `POST` | `/gap` | Silence between sentences (seconds). Persisted to `gap.txt` |
| `POST` | `/nosplit` | Don't split sentences at or below this character count. Persisted to `nosplit.txt` |
| `POST` | `/firstcut` | Target character count for early cutoff of the first sentence (0 to disable). Persisted to `firstcut.txt` |
| `POST` | `/pause` | Cap on in-audio pauses (seconds, 0 for no processing). Persisted to `pause.txt` |
| `GET`·`POST` | `/model` | Query / switch the model in use |
| `GET`·`POST` | `/cache` | Query the audio cache / turn it on/off / clear it (`{"action":"clear"}`) |
| `POST` | `/toggle` | Toggle automatic read-aloud (`tts_auto.flag`) |
| `GET`  | `/vram` | VRAM usage status (total / NoaTTS / free) |
| `POST` | `/quit` | Shuts down the daemon |
| `GET`  | `/health` | Operating status (JSON with voice, speech speed, each adjustment value, model, etc.) |
| `GET`  | `/voices` | List of voices |

In the `/say` JSON, besides `text`, you can specify `volume` (0.0–1.0), `caption` (overrides emotion for that read-aloud only, for Irodori cloning), and `cache` (true/false, overrides cache use for that call only).

> 💾 **Audio cache**: The same combination of "text + voice + speech speed + emotion" reuses an already-synthesized WAV and returns instantly. Enable it with `tts_cache.flag` or `POST /cache {"enabled":true}`.

### OpenAI TTS API compatible (`/v1/audio/speech`)

From an existing OpenAI Text-to-Speech client, you can swap in NoaTTS just by pointing the base URL at `http://127.0.0.1:7870/v1`. For `voice`, use a NoaTTS voice card name; `response_format` supports **`wav` / `mp3` / `flac` / `ogg` / `opus` / `aac` / `pcm`** (formats with no encoder in your environment fall back to `wav`).

```bash
curl http://127.0.0.1:7870/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"input":"こんにちは、ノアです","voice":"noa","response_format":"wav"}' --output out.wav
```

Examples:

```bash
# Plain text
curl -X POST http://127.0.0.1:7870/say -d "テストです。聞こえていますか？"

# JSON (with volume and emotion)
curl -X POST http://127.0.0.1:7870/say -H "Content-Type: application/json" \
  -d "{\"text\": \"おかえりなさい\", \"volume\": 0.8}"
```

Emojis, markdown symbols, and code blocks are stripped automatically on send (emotion emojis are kept).

### Automatic read-aloud (file watching)

While the `tts_auto.flag` file exists, changes to the contents of `_tts_say.txt` are read aloud automatically. Use this when you want an external script to read aloud by "just writing text to a file." Without the flag it's ignored (HTTP / pipe always read aloud regardless of the flag).

---

## Emotion emojis (Irodori)

In the Irodori engine, embedding emotion emojis in the read-aloud text lets **only the emotion ride on top while the voice (reference audio) stays the same**. Repeating the same emoji strengthens the effect (measured: a single 😭 increases audio length by +30%, 😭×3 by +130%). Ordinary decorative emojis are stripped, but these emotion emojis are kept and interpreted.

| Emoji | Effect | Emoji | Effect |
|---|---|---|---|
| 😭 | Crying | 🤭 | Stifled chuckle |
| 😱 | Scream | 😮‍💨 | Sigh / breath |
| 😠 | Anger | 👂 | Whisper |
| 😰 | Agitation | 🌬️ | Out of breath |
| 🥺 | Trembling voice | ⏩ / 🐢 | Fast / slow |

You can also insert them from the emoji palette in the Web UI.

---

## Batch line generation

Load a script (CSV / Excel), assign a voice to each character that appears, and generate audio files all at once (for creating lines for videos, games, etc.). The character⇔voice assignments can be saved as a **preset** to `presets/<name>.json` and recalled. You operate this from the "Batch line generation" tab in the Web UI.

Sample scripts (with filled-in examples): [sample_script.xlsx](sample_script.xlsx) (Excel · recommended) / [sample_script.csv](sample_script.csv) (CSV). Both can also be opened in Google Sheets. Pressing the "Create template" button loads this sample straight into the line table on the spot, so you can edit it and "Overwrite save" directly (downloading is also possible).

Script columns (any order · auto-recognized by header name):

| Column | Required | Description |
|---|---|---|
| `ID` | ○ | Sequential number. Starting it with `■` turns it into a separator heading row excluded from generation |
| `Character (personality)` | ○ | Describe the voice's personality in prose. Characters with the **same string** are assigned the same voice |
| `Filename` | ○ | Output WAV name. Half-width alphanumerics and `_ - .` recommended (full-width characters and symbols are stripped) |
| `Line` | ○ | The body text to read aloud |
| `Line kana` | | Override only words whose reading is uncertain, with kana (optional) |
| `Emotion` | | Joy / anger / sorrow / fun, etc. (optional) |
| `Qwen3 TTS system prompt` | | Instructions for the manner of speaking and tone (optional) |
| `Recommended` | | Put `★` to mark it as a candidate. The count is tallied on load |

### Automatic post-generation check (bonus feature)

It **matches the lines with Whisper** against the generated audio and also checks the **voice's gender (F0)**. Lines that fail are automatically **retried up to 3 times** with adjusted instructions. It also supports generating **only `★` rows**, a ⚠️ warning when a single line is too long, per-line regeneration, and an NG report (`ng_report.txt` / Excel export of the failing rows).

> ⚠️ **This check is not perfect.** Whisper's transcription and the F0 judgment can be wrong — it may flag correct audio as NG, or vice versa. **Use it only as a rough guide** and confirm the final selection with your ears.

---

## Voice cards

Place each voice's `config.json` (speaker, seed, reference audio, speech speed, etc.) and its reference audio under `voices/<name>/`. You can create and edit them from the Web UI (`run.bat`).

> ⚠️ **About the bundled voice**: The only voice bundled in this repository is `noa` (self-made). If you redistribute it with a voice you cloned (using a third party's recording as the reference audio), check the rights yourself.

---

## Folder structure (for developers)

The code is organized into packages by feature. The entry points and the settings-path baseline (`config.py`) remain directly at the root.

```
engine/   TTS synthesis core (tts_engine, irodori_engine, engine_control, audio_utils, models_catalog, emotion_emoji, text_utils)
voice/    Voice management (voice_manager, voice_creation, preset_manager)
ui/       Voice Studio UI parts (mascot, ui_voice_create/)
daemon/   Read-aloud daemon
batch/    Batch line generation
conf/     Settings & reading dictionary (settings.json※ / settings.default.json / reading_dict.json)
tests/    Tests
assets/ docs/ voices/ presets/   Assets & data
```

The `.py` files directly at the root are the entry points (`app.py` / `tray.py` / `noa_tts_daemon.py` / `noa_launcher.py` / `tts_api_window.py` / `webview_window.py` / `download_models.py`) and the foundation referenced throughout (`config.py`). The `bat` files and `NoaTTS.exe` launch these by filename, so they haven't been moved.

> ※ `conf/settings.json` is generated by copying from `conf/settings.default.json` on first launch and is rewritten by user settings thereafter, so it's not under git management.

---

## Changelog

For changes, see [CHANGELOG.md](CHANGELOG.md). The latest version is **v1.2.0** (one-click distribution · portable version).

---

## License

This app's code is distributed under the [MIT License](LICENSE).
The licenses of the TTS models and bundled voices follow the terms of their respective providers.

- **Irodori-TTS** (default engine) — both code and model are under the **MIT license** and **commercial use is allowed** ([code](https://github.com/Aratako/Irodori-TTS) / [model card](https://huggingface.co/Aratako/Irodori-TTS-500M-v3)).
  However, **cloning the voice of a real person (voice actors, celebrities, etc.) without their consent, and creating deepfakes or misinformation, is prohibited**.
- **Qwen3-TTS** — please check the license of each provider ([Qwen3-TTS-streaming](https://github.com/dffdeeq/Qwen3-TTS-streaming) / [Qwen official](https://huggingface.co/Qwen)).

> ⚠️ The final permissibility of use (including commercial use) **depends on the licenses of the model you use, the source audio you cloned from, and each dependent component — please confirm and decide for yourself**. This project bears no responsibility for the results of such use.
