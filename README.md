# VoiceScribe

Local meeting transcription with speaker identification for Windows. Records system audio (desktop speakers/microphone), transcribes speech using Whisper, and identifies speakers -- all running entirely on your machine with no cloud dependencies.

## Prerequisites

- **Python 3.11+**
- **Node.js 18+** and npm
- **GPU (optional):** NVIDIA GPU with CUDA for faster transcription. CPU works but is slower.
- **Windows 10/11** (uses WASAPI loopback for system audio capture)

## Quick Start (Development)

1. **Install Python dependencies:**

```bash
cd backend
pip install -e .
```

2. **Install frontend dependencies:**

```bash
cd frontend
npm install
```

3. **Run in dev mode** (starts both backend and Electron):

```bash
dev.bat
```

Or start each part manually:

```bash
# Terminal 1 — Python backend
cd backend
python -m src.main serve

# Terminal 2 — Electron + Vite
cd frontend
npm run electron:dev
```

## CLI Usage

The backend also works as a standalone CLI tool:

```bash
cd backend

# List audio devices
python -m src.main devices

# Record and transcribe
python -m src.main record --duration 60

# Transcribe a WAV file
python -m src.main transcribe --file meeting.wav

# List saved meetings
python -m src.main meetings

# Export a transcript
python -m src.main export --meeting-id <id> --format md --output transcript.md
```

## Build for Distribution

Run the build script to produce a standalone Windows installer:

```bash
build.bat
```

This will:
1. Install Python dependencies
2. Bundle the Python backend with PyInstaller
3. Build the React frontend with Vite
4. Package everything into an Electron installer via electron-builder

The output installer is located at `frontend/dist/VoiceScribe Setup*.exe`.

## Project Structure

```
BlaBlaLog/
  backend/              Python backend
    src/
      audio/            Audio capture (WASAPI), VAD (Silero)
      transcription/    Whisper transcription engine
      speakers/         Speaker diarization and identification
      storage/          SQLite database, export (md/txt/srt/json)
      utils/            Config, logging
      ipc.py            JSON-RPC server for Electron communication
      main.py           CLI entry point
    voicescribe.spec    PyInstaller build spec
    pyproject.toml      Python package config
    requirements.txt    Flat pip requirements
  frontend/             Electron + React (Vite)
    electron/           Electron main process (main.js, preload.js)
    src/                React UI
    package.json        Node dependencies and electron-builder config
  build.bat             Full production build script
  dev.bat               Development mode launcher
  models/               Downloaded ML models (auto-created)
  docs/                 Architecture and planning docs
```

## Configuration

The backend reads settings from environment variables or a `.env` file in the backend directory. Key settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `WHISPER_MODEL` | `base` | Whisper model size (`tiny`, `base`, `small`, `medium`, `large-v3`) |
| `WHISPER_DEVICE` | `auto` | Compute device (`auto`, `cpu`, `cuda`) |
| `LANGUAGE` | `en` | Transcription language code |
| `SAMPLE_RATE` | `16000` | Audio sample rate in Hz |

## License

Private -- all rights reserved.
