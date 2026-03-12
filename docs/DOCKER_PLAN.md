# VoiceScribe — Docker Deployment Plan

## Цель

Упаковать VoiceScribe в Docker-контейнер и опубликовать на Docker Hub,
чтобы любой пользователь (Windows / macOS / Linux) мог запустить одной командой:

```bash
docker run -d -p 3000:3000 -v voicescribe-data:/app/data --name voicescribe voicescribe/voicescribe:latest
```

Открыть `http://localhost:3000` — и всё работает.

---

## Проблема: Electron ≠ Docker

Текущая архитектура — **десктопное Electron-приложение**. Docker не может:
- Показать GUI-окно Electron на хосте
- Захватить аудиоустройства хоста (WASAPI/CoreAudio/PulseAudio)

**Решение:** Перейти на **веб-архитектуру** (как Uptime Kuma, Immich, Ollama WebUI):

| Сейчас (Electron) | Docker (Web) |
|---|---|
| Electron main.js запускает Python | Python (FastAPI) сервер — точка входа |
| React рендерится в BrowserWindow | React раздаётся как static files |
| Аудио: PyAudioWPatch (WASAPI) | Аудио: Browser MediaRecorder API |
| IPC: JSON-RPC over stdio | API: REST + WebSocket |
| Запуск: VoiceScribe.exe | Запуск: `docker run ...` → браузер |

---

## Архитектура Docker-версии

```
┌─────────────────────────────────────────────┐
│  Docker Container                           │
│                                             │
│  ┌────────────────────────────────────────┐ │
│  │  FastAPI Server (:3000)                │ │
│  │                                        │ │
│  │  GET /           → React SPA (static)  │ │
│  │  WS  /ws/audio   → Приём аудио-потока  │ │
│  │  POST /api/upload → Загрузка WAV/MP3   │ │
│  │  GET  /api/meetings → REST API         │ │
│  │  WS   /ws/status  → Прогресс/события   │ │
│  └────────────┬───────────────────────────┘ │
│               │                             │
│  ┌────────────▼───────────────────────────┐ │
│  │  Transcription Engine                  │ │
│  │  faster-whisper (small/medium)         │ │
│  │  + VAD + Speaker clustering            │ │
│  └────────────┬───────────────────────────┘ │
│               │                             │
│  ┌────────────▼───────────────────────────┐ │
│  │  SQLite DB  (/app/data/voicescribe.db) │ │
│  │  + Audio files (/app/data/audio/)      │ │
│  └────────────────────────────────────────┘ │
│                                             │
│  Volume: /app/data (persistent)             │
└─────────────────────────────────────────────┘

┌──────────────────────────────┐
│  Browser (хост-машина)       │
│                              │
│  React SPA                   │
│  - getUserMedia() → микрофон │
│  - getDisplayMedia() → табы  │
│  - MediaRecorder → WebSocket │
│  - UI: запись, транскрипт,   │
│    история, настройки        │
└──────────────────────────────┘
```

---

## Что нужно изменить в коде

### 1. Backend: JSON-RPC stdio → FastAPI HTTP/WebSocket

**Файл:** `backend/src/server.py` (новый)

```
Создать FastAPI-приложение:
- Статика: React build из /app/frontend/dist
- REST API: /api/meetings, /api/speakers, /api/settings, /api/export
- WebSocket: /ws/audio (приём аудио-чанков в реальном времени)
- WebSocket: /ws/status (отправка прогресса, событий)
- POST /api/upload (загрузка готового аудиофайла)
```

**Объём работ:** ~300 строк. Большая часть логики уже в `ipc.py` —
нужно обернуть те же методы в HTTP-эндпоинты.

### 2. Frontend: Electron IPC → fetch/WebSocket

**Изменения:**

| Файл | Что менять |
|---|---|
| `hooks/useBackend.ts` | `electronAPI.sendToBackend()` → `fetch("/api/...")` |
| `hooks/useBackend.ts` | `electronAPI.onBackendEvent()` → `new WebSocket("/ws/status")` |
| `components/RecordingPanel.tsx` | PyAudioWPatch → `navigator.mediaDevices.getUserMedia()` |
| `components/RecordingPanel.tsx` | Loopback → `navigator.mediaDevices.getDisplayMedia()` |
| `App.tsx` | Убрать `WindowControls` (нет Electron окна) |
| `types.ts` | Убрать `ElectronAPI` |

**Объём работ:** ~200 строк изменений. UI компоненты остаются как есть.

### 3. Аудио-захват в браузере

```
Микрофон:
  navigator.mediaDevices.getUserMedia({ audio: true })
  → MediaRecorder → WebSocket → backend

Системный звук (звук из вкладки/экрана):
  navigator.mediaDevices.getDisplayMedia({ audio: true, video: false })
  → MediaRecorder → WebSocket → backend
  ⚠️ Ограничение: только Chrome/Edge, требует выбора вкладки/экрана
  ⚠️ На macOS нет системного аудио через getDisplayMedia
```

**Альтернатива для системного звука:**
- Пользователь записывает аудио отдельно → загружает WAV/MP3 через UI
- Virtual Audio Cable (пользователь настраивает сам)

### 4. Dockerfile

```dockerfile
# Stage 1: Build frontend
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# Stage 2: Python backend
FROM python:3.11-slim
WORKDIR /app

# System deps for audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libsndfile1 && \
    rm -rf /var/lib/apt/lists/*

# Python deps
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/src/ /app/src/

# Copy built frontend
COPY --from=frontend-build /app/frontend/dist /app/static

# Pre-download Whisper model (so first run is fast)
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('small')"

# Data volume
VOLUME /app/data

EXPOSE 3000

CMD ["python", "-m", "uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "3000"]
```

### 5. docker-compose.yml

```yaml
version: "3.8"

services:
  voicescribe:
    image: voicescribe/voicescribe:latest
    container_name: voicescribe
    restart: unless-stopped
    ports:
      - "3000:3000"
    volumes:
      - voicescribe-data:/app/data
    environment:
      - VOICESCRIBE_WHISPER_MODEL=small    # tiny/small/medium/large-v2
      - VOICESCRIBE_LANGUAGE=auto          # auto/en/ru/uk/es
    # GPU support (optional):
    # deploy:
    #   resources:
    #     reservations:
    #       devices:
    #         - capabilities: [gpu]

volumes:
  voicescribe-data:
```

---

## Установка (как будет выглядеть для пользователя)

### 🐳 Docker

```bash
docker run -d \
  --restart=unless-stopped \
  -p 3000:3000 \
  -v voicescribe-data:/app/data \
  --name voicescribe \
  voicescribe/voicescribe:latest
```

Откройте `http://localhost:3000` в браузере.

**С GPU (NVIDIA):**

```bash
docker run -d \
  --restart=unless-stopped \
  --gpus all \
  -p 3000:3000 \
  -v voicescribe-data:/app/data \
  --name voicescribe \
  voicescribe/voicescribe:latest
```

### 🐳 Docker Compose

```bash
mkdir voicescribe && cd voicescribe
curl -o docker-compose.yml https://raw.githubusercontent.com/user/voicescribe/main/docker-compose.yml
docker compose up -d
```

### Обновление

```bash
docker pull voicescribe/voicescribe:latest
docker stop voicescribe
docker rm voicescribe
docker run -d --restart=unless-stopped -p 3000:3000 -v voicescribe-data:/app/data --name voicescribe voicescribe/voicescribe:latest
```

### Параметры

| Переменная | По умолчанию | Описание |
|---|---|---|
| `VOICESCRIBE_WHISPER_MODEL` | `small` | Модель Whisper: tiny/small/medium/large-v2 |
| `VOICESCRIBE_LANGUAGE` | `auto` | Язык: auto/en/ru/uk/es |
| `VOICESCRIBE_PORT` | `3000` | Порт веб-интерфейса |
| `-v /app/data` | — | **Обязательно!** Данные, БД, аудиофайлы |

---

## Размер Docker-образа (оценка)

| Компонент | Размер |
|---|---|
| python:3.11-slim | ~150 MB |
| faster-whisper + deps | ~200 MB |
| Whisper model (small) | ~500 MB |
| torch (CPU) | ~800 MB |
| Frontend (React build) | ~1 MB |
| **Итого** | **~1.6 GB** |

С GPU (CUDA): ~4 GB.

---

## План реализации (этапы)

### Этап 1 — FastAPI сервер (backend)
- [ ] Создать `backend/src/server.py` — FastAPI app
- [ ] REST endpoints: перенести методы из `ipc.py`
- [ ] WebSocket `/ws/audio` — приём аудио-чанков
- [ ] WebSocket `/ws/status` — отправка событий
- [ ] POST `/api/upload` — загрузка аудиофайлов
- [ ] Раздача статики React из `/app/static`
- [ ] Тест: `uvicorn src.server:app` работает

### Этап 2 — Frontend web-mode
- [ ] `useBackend.ts` — режим fetch/WebSocket (вместо Electron IPC)
- [ ] `RecordingPanel.tsx` — `getUserMedia()` + `getDisplayMedia()` + MediaRecorder
- [ ] `App.tsx` — убрать Electron-специфику (WindowControls) в web-mode
- [ ] Автодетект: Electron или браузер (оба режима работают)
- [ ] Тест: `npm run dev` → `http://localhost:5173` → запись работает

### Этап 3 — Dockerfile + docker-compose
- [ ] Multi-stage Dockerfile (node build → python runtime)
- [ ] Pre-download Whisper model в образ
- [ ] docker-compose.yml с volumes и env vars
- [ ] Тест: `docker build . && docker run` — всё работает
- [ ] GPU вариант (CUDA base image)

### Этап 4 — Docker Hub + документация
- [ ] Создать Docker Hub репозиторий `voicescribe/voicescribe`
- [ ] CI/CD: GitHub Actions → автосборка → push на Docker Hub
- [ ] README.md с инструкциями установки (по примеру Uptime Kuma)
- [ ] Теги: `latest`, `0.1.0`, `gpu`

### Этап 5 — Кросс-платформенность
- [ ] Тест на macOS (Docker Desktop)
- [ ] Тест на Linux (Docker Engine)
- [ ] Тест на Windows (Docker Desktop / WSL2)
- [ ] Multi-arch image: `linux/amd64` + `linux/arm64` (Apple Silicon)

---

## Ограничения Docker-версии vs Desktop

| Фича | Desktop (Electron) | Docker (Web) |
|---|---|---|
| Запись микрофона | ✅ PyAudio | ✅ getUserMedia |
| Системный звук | ✅ WASAPI Loopback | ⚠️ getDisplayMedia (только Chrome) |
| macOS системный звук | ❌ | ❌ (ограничение ОС) |
| Загрузка аудиофайлов | ❌ | ✅ drag & drop / upload |
| Frameless window | ✅ | ❌ (браузер) |
| Tray icon | ✅ | ❌ |
| Offline | ✅ | ✅ (localhost) |
| Multi-user | ❌ | ✅ (потенциально) |
| Удалённый доступ | ❌ | ✅ (через IP/VPN) |

---

## Совместимость обоих режимов

Можно сохранить **оба варианта** (Desktop + Docker) с общей кодовой базой:

```
frontend/src/hooks/useBackend.ts:

const isElectron = typeof window.electronAPI !== 'undefined';

if (isElectron) {
  // Electron mode: JSON-RPC over IPC
  return window.electronAPI.sendToBackend(method, params);
} else {
  // Web mode: REST API
  return fetch(`/api/${method}`, { method: 'POST', body: JSON.stringify(params) });
}
```

Так не ломается текущий Electron-билд, и добавляется Docker-версия.
