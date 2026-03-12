# VoiceScribe — Architecture Overview

## Project Structure (Current)

```
voicescribe/
├── .gitignore
├── docs/
│   ├── PROJECT_PLAN.md          # Полный план с прогрессом
│   └── ARCHITECTURE.md          # Этот файл
│
├── backend/
│   ├── pyproject.toml            # Python dependencies
│   ├── src/
│   │   ├── __init__.py
│   │   ├── main.py               # CLI entry point (record/devices/transcribe/meetings/export/serve)
│   │   ├── ipc.py                # JSON-RPC 2.0 over stdio (Tauri ↔ Python)
│   │   ├── audio/
│   │   │   ├── __init__.py
│   │   │   ├── capture.py        # WASAPI Loopback — захват системного звука
│   │   │   └── vad.py            # Silero VAD — детекция речи
│   │   ├── transcription/
│   │   │   ├── __init__.py
│   │   │   └── engine.py         # faster-whisper — STT с таймстемпами
│   │   ├── speakers/
│   │   │   └── __init__.py       # (Phase 2-3: diarization, embeddings, identifier)
│   │   ├── storage/
│   │   │   ├── __init__.py
│   │   │   ├── models.py         # Pydantic: Speaker, Meeting, Segment
│   │   │   ├── database.py       # Async SQLite CRUD
│   │   │   └── export.py         # Export to txt/md/srt/json
│   │   └── utils/
│   │       ├── __init__.py
│   │       ├── config.py         # Pydantic Settings (env: VOICESCRIBE_*)
│   │       └── logger.py         # Logging setup
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py           # Shared fixtures
│       ├── test_capture.py       # 9 tests
│       ├── test_transcription.py # 9 tests
│       └── test_storage.py       # 22 tests
│
└── models/                       # (gitignored) ML models cache
```

## Data Flow

```
System Audio (WASAPI Loopback)
        │
        ▼
  AudioCapture (16kHz mono float32, ring buffer)
        │
        ▼
  Silero VAD (speech segments extraction)
        │
        ▼
  faster-whisper (text + timestamps + confidence)
        │
        ▼
  SQLite Database (meetings → segments → speakers)
        │
        ▼
  Export (txt / md / srt / json)
```

## IPC Protocol (JSON-RPC 2.0)

Frontend (Tauri/React) communicates with Python backend via stdio:

```
Frontend → stdin  → {"jsonrpc":"2.0","method":"start_recording","params":{},"id":1}
Backend  → stdout → {"jsonrpc":"2.0","result":{"meeting_id":"..."},"id":1}
Backend  → stdout → {"jsonrpc":"2.0","method":"transcript.partial","params":{"text":"..."}}
```

## Phase Status

| Phase | Status | Description |
|-------|--------|-------------|
| 1 | ✅ Done | Audio capture + transcription + storage + CLI |
| 2 | ⬜ Next | Speaker diarization (pyannote-audio) |
| 3 | ⬜ Planned | Speaker identification (ECAPA-TDNN) |
| 4 | ⬜ Planned | Real-time streaming |
| 5 | ⬜ Planned | GUI (Tauri + React) |
| 6 | ⬜ Planned | Polish & extras |
