# VoiceScribe — Локальная транскрипция созвонов для Windows

## Описание проекта

Десктопное приложение для Windows, которое записывает аудио (микрофон + системный звук) из Teams/Discord/Zoom, транскрибирует после остановки записи (Record → Transcribe), автоматически определяет спикеров по источнику аудио (микрофон / системный звук), поддерживает мультиязычную транскрипцию с автоопределением языка по 30-секундным чанкам, и сохраняет структурированные протоколы встреч. Всё работает локально, без отправки данных в облако.

---

## Стек технологий

- **Язык ядра:** Python 3.11+
- **Захват аудио:** PyAudioWPatch (WASAPI Loopback) + sounddevice (микрофон) — dual capture
- **STT:** faster-whisper (CTranslate2, модель small по умолчанию, beam_size=1 greedy)
- **Мультиязычность:** Автоопределение языка по 30-сек чанкам (Auto-detect, English, Russian, Ukrainian, Spanish)
- **VAD:** Встроенный Silero VAD в faster-whisper (vad_filter=True)
- **Диаризация:** pyannote-audio 3.1
- **Speaker ID:** По источнику аудио (микрофон vs системный звук) + speechbrain ECAPA-TDNN (голосовые отпечатки)
- **БД:** SQLite (транскрипты, профили спикеров, embeddings)
- **GUI:** Electron 28 + React 19 + TypeScript + Vite 7 + Zustand (state management)
- **IPC:** sidecar-процесс Python ↔ Electron через JSON-RPC 2.0 over stdio (child_process)
- **Сборка:** electron-builder (portable .exe, без установки)

---

## Структура проекта

```
VoiceScribe/
├── README.md
├── VoiceScribe.bat              # Быстрый запуск (dev)
├── VoiceScribe.vbs              # Скрытый запуск без консоли
├── build.bat                    # Полная сборка
├── build-portable.bat           # Portable build
├── dev.bat                      # Dev-режим
│
├── docs/
│   ├── PROJECT_PLAN.md          # Этот файл
│   ├── ARCHITECTURE.md          # Архитектурная документация
│   └── PRESENTATION.md          # Презентация проекта
│
├── backend/                     # Python ядро
│   ├── requirements.txt         # pip-зависимости
│   ├── src/
│   │   ├── __init__.py
│   │   ├── main.py              # Точка входа (CLI + sidecar serve)
│   │   ├── ipc.py               # JSON-RPC 2.0 обработчик stdio
│   │   ├── audio/
│   │   │   ├── __init__.py
│   │   │   ├── capture.py       # WASAPI Loopback захват (системный звук)
│   │   │   ├── microphone.py    # sounddevice захват микрофона
│   │   │   ├── mixer.py         # Микширование system + mic (50/50)
│   │   │   └── vad.py           # Silero VAD (legacy, не используется в batch)
│   │   ├── transcription/
│   │   │   ├── __init__.py
│   │   │   ├── engine.py        # faster-whisper wrapper + multilingual
│   │   │   └── streaming.py     # Streaming transcriber (legacy)
│   │   ├── speakers/
│   │   │   ├── __init__.py
│   │   │   ├── diarization.py   # pyannote диаризация
│   │   │   ├── embeddings.py    # speechbrain ECAPA-TDNN
│   │   │   ├── identifier.py    # Cosine similarity, threshold 0.70
│   │   │   └── profiles.py      # CRUD для голосовых профилей
│   │   ├── storage/
│   │   │   ├── __init__.py
│   │   │   ├── database.py      # SQLite (aiosqlite, WAL mode)
│   │   │   ├── models.py        # Pydantic: Meeting, Segment, Speaker
│   │   │   └── export.py        # Экспорт в txt/md/srt/json
│   │   └── utils/
│   │       ├── __init__.py
│   │       ├── config.py        # Pydantic Settings (VOICESCRIBE_ prefix)
│   │       └── logger.py        # Логирование
│   └── data/                    # SQLite БД, аудиофайлы (runtime)
│
├── frontend/                    # Electron + React UI
│   ├── package.json             # npm deps + electron-builder config
│   ├── electron/
│   │   ├── main.js              # Electron main process + Python sidecar
│   │   └── preload.js           # Preload-скрипт (IPC bridge)
│   ├── src/
│   │   ├── App.tsx              # Навигация, frameless window controls
│   │   ├── main.tsx             # React entry point
│   │   ├── types.ts             # TypeScript типы
│   │   ├── components/
│   │   │   ├── RecordingPanel.tsx    # Запись: dual device selectors, VU meter, таймер
│   │   │   ├── LiveTranscript.tsx    # Транскрипт с цветовой маркировкой
│   │   │   ├── LogViewer.tsx         # Просмотр логов приложения
│   │   │   ├── SpeakerList.tsx       # Список спикеров + аватары
│   │   │   ├── SpeakerTraining.tsx   # Обучение голосовых профилей
│   │   │   ├── MeetingHistory.tsx    # Архив встреч + поиск
│   │   │   ├── MeetingDetail.tsx     # Детали одной встречи
│   │   │   ├── Settings.tsx          # Настройки: модель, язык, устройства
│   │   │   └── ExportDialog.tsx      # Экспорт в разные форматы
│   │   ├── hooks/
│   │   │   └── useBackend.ts         # IPC с Python sidecar (JSON-RPC)
│   │   ├── stores/
│   │   │   └── appStore.ts           # Zustand — глобальный стейт
│   │   └── styles/
│   │       └── globals.css           # Dark theme (Discord/Spotify стиль)
│   └── tsconfig.json
│
└── release/                     # Собранное приложение (gitignored)
    └── 0.0.4/win-unpacked/
        ├── VoiceScribe.exe
        └── resources/
            ├── app/             # Electron + React bundle
            └── backend/         # Python + .venv + модели
```

---

## Схема базы данных

```sql
CREATE TABLE speakers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    embedding BLOB NOT NULL,        -- numpy array serialized
    sample_audio_path TEXT,          -- путь к образцу голоса
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE meetings (
    id TEXT PRIMARY KEY,
    title TEXT,
    started_at DATETIME NOT NULL,
    ended_at DATETIME,
    duration_seconds INTEGER,
    audio_path TEXT,                 -- путь к записи (опционально)
    language TEXT DEFAULT 'ru',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id TEXT NOT NULL REFERENCES meetings(id),
    speaker_id TEXT REFERENCES speakers(id),
    speaker_label TEXT,             -- "Speaker 1" если не опознан
    start_time REAL NOT NULL,       -- секунды от начала
    end_time REAL NOT NULL,
    text TEXT NOT NULL,
    confidence REAL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_segments_meeting ON segments(meeting_id);
CREATE INDEX idx_segments_speaker ON segments(speaker_id);
```

---

## Фазы разработки

### Фаза 1 — Захват аудио и базовая транскрипция

**Цель:** Записать системный звук → получить текст.

**Задачи:**

- [x] ✅ Инициализировать проект: pyproject.toml, структура папок, .gitignore (2026-03-12)
- [x] ✅ Реализовать `utils/config.py` — Pydantic Settings с VOICESCRIBE_ prefix (2026-03-12)
- [x] ✅ Реализовать `utils/logger.py` — логирование с настраиваемым уровнем (2026-03-12)
- [x] ✅ Реализовать `audio/capture.py` — WASAPI Loopback через PyAudioWPatch (2026-03-12)
  - Перечисление аудиоустройств (list_devices, list_loopback_devices)
  - Захват в кольцевой буфер (ring buffer 300с)
  - Ресемплинг в 16kHz mono float32
  - Context manager support
- [x] ✅ Реализовать `audio/vad.py` — Silero VAD (2026-03-12)
  - Фильтрация тишины, выделение фрагментов с речью
  - Настройка порогов: min_speech_duration, min_silence_duration
  - Методы: process(), is_speech(), reset()
- [x] ✅ Реализовать `transcription/engine.py` — faster-whisper (2026-03-12)
  - Загрузка модели (medium по умолчанию, auto-detect GPU/CPU)
  - Транскрипция аудио-чанков с таймстемпами и confidence
  - Определение языка (detect_language)
- [x] ✅ Реализовать `storage/models.py` — Pydantic модели (Speaker, Meeting, Segment, TranscriptLine) (2026-03-12)
- [x] ✅ Реализовать `storage/database.py` — SQLite через aiosqlite (2026-03-12)
  - Создание таблиц при первом запуске (WAL mode, foreign keys)
  - Полный CRUD для meetings, segments, speakers
  - Async context manager
- [x] ✅ Реализовать `storage/export.py` — экспорт в txt/md/srt/json (2026-03-12)
- [x] ✅ Реализовать `ipc.py` — JSON-RPC 2.0 over stdio (2026-03-12)
  - 11 методов: ping, get_devices, start/stop_recording, get_status, meetings CRUD, export
  - Notification support для стриминга событий
- [x] ✅ Написать CLI-скрипт `main.py` с subcommands (2026-03-12)
  - record, devices, transcribe, meetings, export, serve
  - Полный пайплайн: запись → VAD → транскрипция → сохранение → экспорт
- [x] ✅ Тесты: 40+ тестов для capture, transcription, storage, export (2026-03-12)

**Зависимости для фазы 1:**

```
faster-whisper>=1.1.0
PyAudioWPatch>=0.2.13
silero-vad>=5.1
numpy>=1.26
aiosqlite>=0.20
pydantic>=2.0
pydantic-settings>=2.0
```

**Критерий готовности:** Запускаем скрипт → включаем видео на YouTube → получаем текстовый файл с транскрипцией.

---

### Фаза 2 — Диаризация спикеров

**Цель:** Разделить аудио по спикерам ("Speaker 1", "Speaker 2").

**Задачи:**

- [x] ✅ Реализовать `speakers/diarization.py` — pyannote-audio wrapper (2026-03-12)
  - Graceful degradation если модель недоступна
  - `diarize()` / `diarize_file()` — выдаёт список {speaker, start, end}
  - `merge_with_transcription()` — maximum overlap strategy
- [x] ✅ Интеграция с транскрипцией в IPC (2026-03-12)
  - Диаризация запускается после остановки записи
  - Совмещение таймстемпов Whisper и pyannote
- [x] ✅ Storage уже поддерживает speaker_label в segments (Phase 1)

**Дополнительные зависимости:**

```
pyannote.audio>=3.1
torch>=2.1
torchaudio>=2.1
```

**Критерий готовности:** Записываем созвон с двумя+ людьми → каждая реплика правильно привязана к своему спикеру.

---

### Фаза 3 — Идентификация спикеров по голосу

**Цель:** Заменить "Speaker 1" на реальные имена.

**Задачи:**

- [x] ✅ Реализовать `speakers/embeddings.py` — ECAPA-TDNN 192-dim embeddings (2026-03-12)
- [x] ✅ Реализовать `speakers/profiles.py` — CRUD профилей, усреднение embeddings (2026-03-12)
- [x] ✅ Реализовать `speakers/identifier.py` — cosine similarity, threshold 0.70 (2026-03-12)
- [x] ✅ IPC методы: create_speaker_profile, train_speaker_from_segment, delete_speaker (2026-03-12)
- [x] ✅ Интеграция: после диаризации → идентификация кластеров → замена меток (2026-03-12)

**Дополнительные зависимости:**

```
speechbrain>=1.0
scikit-learn>=1.4          # cosine_similarity
```

**Критерий готовности:** После обучения на 2-3 образцах → система узнаёт знакомые голоса по имени.

---

### Фаза 4 — Real-time стриминг

**Цель:** Транскрипция в реальном времени, а не пост-обработка.

**Задачи:**

- [x] ✅ Реализовать `transcription/streaming.py` — VAD-based chunking + overlap (2026-03-12)
- [x] ✅ Реализовать `audio/microphone.py` — sounddevice захват микрофона (2026-03-12)
- [x] ✅ Реализовать `audio/mixer.py` — микширование system + mic (2026-03-12)
- [x] ✅ IPC стриминг: transcript.partial, transcript.final, processing.status (2026-03-12)
- [x] ✅ Background asyncio task для feed аудио → streamer (2026-03-12)

**Критерий готовности:** Текст появляется на экране с задержкой < 3 секунд от произнесения.

---

### Фаза 5 — GUI (Electron + React)

**Цель:** Полноценное десктопное приложение.

> **Примечание:** Заменили Tauri на Electron (Rust не установлен на машине разработки).

**Задачи:**

- [x] ✅ Инициализировать Electron + Vite + React + TypeScript проект (2026-03-12)
- [x] ✅ Настроить sidecar: Electron запускает Python через child_process + stdin/stdout JSON-RPC (2026-03-12)
- [x] ✅ RecordingPanel.tsx — старт/стоп, таймер, выбор устройства, live transcript (2026-03-12)
- [x] ✅ LiveTranscript.tsx — автоскролл, цветовая маркировка спикеров (2026-03-12)
- [x] ✅ SpeakerList.tsx — список спикеров, удаление, аватары (2026-03-12)
- [x] ✅ SpeakerTraining.tsx — запись образца, сохранение профиля (2026-03-12)
- [x] ✅ MeetingHistory.tsx + MeetingDetail.tsx — архив, поиск, детали (2026-03-12)
- [x] ✅ Settings.tsx — модель, язык, устройства, порог спикера (2026-03-12)
- [x] ✅ ExportDialog.tsx — экспорт md/txt/srt/json с превью (2026-03-12)
- [x] ✅ Zustand store + useBackend hook + mock fallback для браузера (2026-03-12)
- [x] ✅ Dark theme (Discord/Spotify стиль) — globals.css (2026-03-12)
- [x] ✅ System tray, minimize to tray, single instance lock (2026-03-12)

---

### Фаза 6 — Polish и дополнительные фичи

**Задачи:**

- [x] ✅ System tray + minimize to tray (в electron/main.js) (2026-03-12)
- [x] ✅ IPC интеграция всех speaker features (create/train/delete/identify) (2026-03-12)
- [x] ✅ Real-time streaming через IPC (transcript.partial/final notifications) (2026-03-12)
- [x] ✅ get_settings / update_settings IPC методы (2026-03-12)
- [x] ✅ Build scripts: build.bat, dev.bat, PyInstaller spec (2026-03-12)
- [x] ✅ Исправлены все несоответствия IPC методов frontend ↔ backend (2026-03-12)
- [x] ✅ Исправлена кодировка UTF-8 для кириллицы в stdio pipe (2026-03-12)
- [ ] Автозапуск: опциональный запуск при старте Windows (future)
- [ ] Суммаризация через LLM (future)
- [ ] Автообновление (future)

---

### Фаза 7 — Смена архитектуры: Record → Transcribe + Dual Audio

**Цель:** Переход от нерабочего real-time streaming к надёжному подходу "запись → обработка". Dual audio capture. Исправление багов.

**Решение по архитектуре (принято 2026-03-13 после глубокого анализа):**

> Real-time streaming на CPU без GPU нереалистичен: Whisper medium обрабатывает 2 сек аудио за ~12 сек.
> Вместо этого: записываем аудио в WAV → после остановки обрабатываем batch-режимом.
> Batch-транскрипция в 2-3 раза быстрее streaming (контекст, batched decoding, нет overhead).
>
> Electron остаётся — оправдан для IPC с Python, минимальный bundle (218 KB JS).
> Переход на Rust/C# не нужен — bottleneck в Python ML, не в GUI.

**Найденные критические проблемы в коде:**

1. `streaming.py:117` — VAD пересчитывает ВЕСЬ буфер на каждом feed() → O(n²)
2. `engine.py:128+131` — Двойной VAD (Silero + Whisper vad_filter=True) + beam_size=5
3. `vad.py:129` — VAD сбрасывает state каждый вызов → теряет контекст речи
4. `ipc.py:480` — mic_device_index принимается, но игнорируется (только loopback)
5. `config.py:8` — Модель medium по умолчанию (слишком тяжёлая для CPU)
6. `capture.py:283` — numpy linear interpolation для ресемплинга (медленно)

**Задачи:**

- [x] **7.1 — Переход на Record → Transcribe архитектуру:**
  - [x] Упростить `start_recording`: только AudioCapture + MicrophoneCapture → буфер
  - [x] Убрать StreamingTranscriber из потока записи
  - [x] `stop_recording`: batch `engine.transcribe()` на полном аудио
  - [x] Использовать встроенный `vad_filter=True` в faster-whisper (Silero VAD не используется)
  - [x] Отправлять `processing.status` уведомления с прогрессом
  - [x] UI: прогресс-бар "Transcribing..." после остановки записи

- [x] **7.2 — Оптимизация Whisper (batch mode):**
  - [x] Модель `small` по умолчанию (config.py)
  - [x] `beam_size=1` (greedy) по умолчанию в batch processing
  - [x] `compute_type="int8"` на CPU (проверено, работает)
  - [x] Silero VAD убран из пайплайна — используется только Whisper vad_filter
  - [ ] Добавить в Settings выбор: "Быстрый (small/greedy)" vs "Точный (medium/beam=5)"

- [x] **7.3 — Dual Audio Capture (mic + system одновременно):**
  - [x] RecordingPanel UI: два селектора — "Microphone" и "System Audio (Loopback)"
  - [x] `start_recording` IPC: принимает `mic_device_index` + `loopback_device_index`
  - [x] IPC handler запускает AudioCapture + MicrophoneCapture параллельно
  - [x] Микширование потоков при stop (50/50 mix)
  - [x] VU meter — индикаторы уровня звука для обоих источников

- [x] **7.4 — Длительные записи:**
  - [x] Ring buffer увеличен до 3600с (1 час)
  - [ ] Записывать аудио напрямую в WAV файл (не держать всё в RAM)
  - [ ] Периодическое сохранение WAV чанков на диск

- [x] **7.5 — Исправление багов:**
  - [x] **Таймер останавливается** — stopTimer() вызывается немедленно при клике Stop
  - [x] **Кодировка имён устройств** — _fix_device_name() декодирует cp1251→utf8
  - [x] **Race condition** — upsertLiveSegment() вместо check+add/update
  - [ ] **Нет Error Boundary** в React App
  - [ ] **Silent error swallowing** в useBackend catch blocks

- [x] **7.6 — UI улучшения (Recording page):**
  - [x] VU meter (уровень звука) во время записи
  - [ ] Прогресс-бар обработки после остановки
  - [ ] Показывать оценочное время обработки ("~2 мин для 10 мин аудио")
  - [ ] Опция "Режим транскрипции": быстрый / точный

**Скорость batch-транскрипции (ожидаемая):**

| Модель | 10 мин аудио (CPU) | 30 мин (CPU) | 10 мин (GPU) |
|--------|-------------------|-------------|-------------|
| small + greedy | ~1.5 мин | ~4.5 мин | ~10 сек |
| small + beam=5 | ~3 мин | ~9 мин | ~20 сек |
| medium + beam=5 | ~6 мин | ~18 мин | ~30 сек |

**Критерий готовности:** Записываем mic + system audio → нажимаем стоп → через 2-5 мин получаем полный транскрипт с диаризацией и именами спикеров. Сессия до 1 часа.

---

## Требования к системе

**Минимальные:**
- Windows 10/11
- CPU: 4 ядра
- RAM: 8 GB
- Диск: 5 GB (приложение + модели)
- Без GPU: faster-whisper small + int8 + greedy, batch-обработка после записи

**Рекомендуемые:**
- GPU: NVIDIA с 6+ GB VRAM (RTX 3060 и выше)
- RAM: 16 GB
- CUDA 12.x установлена

---

## Полезные ссылки

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- [whisper.cpp](https://github.com/ggerganov/whisper.cpp)
- [pyannote-audio](https://github.com/pyannote/pyannote-audio)
- [SpeechBrain](https://github.com/speechbrain/speechbrain)
- [Silero VAD](https://github.com/snakers4/silero-vad)
- [PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch)
- [Electron](https://www.electronjs.org/)
- [electron-builder](https://www.electron.build/)

---

## Сборка приложения (Portable Build)

Собирает Electron-приложение + Python-бэкенд в одну папку `release\win-unpacked\`. Результат — `VoiceScribe.exe`, который запускается без установки.

### Требования для сборки

- Node.js 18+
- Python 3.11 (установлен в `C:\Python311`)
- Backend venv уже создан (`backend\.venv\`)

### Шаги сборки

```bash
cd frontend

# 1. Установить npm-зависимости (если ещё не установлены)
npm install

# 2. Собрать фронтенд (Vite → dist/)
npx vite build

# 3. Собрать Electron-приложение + скопировать backend
npx electron-builder --win --dir
```

### Что происходит при сборке

1. **Vite** компилирует React/TypeScript → `frontend/dist/` (HTML + JS + CSS)
2. **electron-builder** упаковывает Electron + `dist/` + `electron/` → `release/win-unpacked/`
3. **extraResources** (настроено в `package.json` → `build.extraResources`) копирует `backend/` → `release/win-unpacked/resources/backend/`, включая:
   - `src/**/*` — Python-код
   - `.venv/**/*` — виртуальное окружение с зависимостями
   - `data/**/*` — база данных и файлы
   - `requirements.txt`

### Структура результата

```
release/win-unpacked/
├── VoiceScribe.exe              # ← Запускать этот файл
├── resources/
│   ├── app/                     # Electron-приложение
│   │   ├── electron/main.js     # Главный процесс
│   │   ├── electron/preload.js  # Preload-скрипт
│   │   ├── dist/                # Собранный фронтенд
│   │   └── package.json
│   └── backend/                 # Python-бэкенд
│       ├── src/                 # Исходный код бэкенда
│       ├── .venv/               # Python venv с зависимостями
│       └── requirements.txt
├── locales/
├── *.dll                        # Chromium/Electron библиотеки
└── LICENSE.electron.txt
```

### Как Electron находит backend

В `electron/main.js` функция `getPythonPath()` ищет Python в нескольких местах:

1. **Packaged** (`app.isPackaged=true`): `process.resourcesPath + "/backend/.venv/Scripts/python.exe"`
2. **Portable/Dev**: `path.resolve(__dirname, "..", "..", "backend")` — backend как sibling папки `app/electron/`

Оба пути ведут в `resources/backend/` при сборке через electron-builder.

### Запуск

Двойной клик по `release\win-unpacked\VoiceScribe.exe` в Проводнике Windows.

> **Важно:** Не запускайте exe из терминала VS Code — переменная окружения `ELECTRON_RUN_AS_NODE=1` (устанавливается VS Code) блокирует запуск Electron как GUI-приложения.

### Пересборка после изменений

```bash
cd frontend

# Только фронтенд изменился:
npx vite build
# Затем скопировать вручную:
# cp -r dist/* ../release/win-unpacked/resources/app/dist/

# Фронтенд + бэкенд (полная пересборка):
npx vite build && npx electron-builder --win --dir
```

### Известные предупреждения при сборке

- `"asar usage is disabled"` — нормально, мы отключили asar для доступа к backend файлам
- `"description is missed in package.json"` — некритично
- `"winCodeSign symlink error"` — ошибка code signing, не влияет на работу (мы не подписываем exe)

---

## Быстрый старт (разработка)

```bash
# 1. Установить Python-зависимости
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 2. Установить npm-зависимости
cd frontend
npm install

# 3. Запустить в dev-режиме
# Вариант A — через bat-файл (из корня проекта):
VoiceScribe.bat

# Вариант B — напрямую:
cd frontend
set ELECTRON_RUN_AS_NODE=
npx electron .
```
