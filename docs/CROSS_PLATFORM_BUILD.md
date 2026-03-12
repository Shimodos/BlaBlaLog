# VoiceScribe — Кроссплатформенная сборка (PyInstaller + Electron)

## Концепция

Упаковать Python-бэкенд в единый исполняемый файл через **PyInstaller**, встроить его внутрь Electron-приложения. Итог — один файл (.exe / .dmg / .AppImage), который пользователь скачивает и запускает **без установки Python, pip, venv**.

```
┌─────────────────────────────────────┐
│         VoiceScribe.exe / .app      │
│  ┌──────────────────────────────┐   │
│  │  Electron (Chromium + Node)  │   │
│  │  ┌────────────────────────┐  │   │
│  │  │  React UI (dist/)      │  │   │
│  │  └────────────────────────┘  │   │
│  │  ┌────────────────────────┐  │   │
│  │  │  voicescribe-backend   │  │   │   ← PyInstaller binary
│  │  │  (Python frozen)       │  │   │
│  │  │  • faster-whisper      │  │   │
│  │  │  • torch + torchaudio  │  │   │
│  │  │  • speechbrain         │  │   │
│  │  │  • sounddevice         │  │   │
│  │  └────────────────────────┘  │   │
│  └──────────────────────────────┘   │
└─────────────────────────────────────┘
```

---

## Проблемы и решения

### 1. Размер файла
| Компонент | Размер |
|-----------|--------|
| Electron | ~180 MB |
| Python + faster-whisper + torch (CPU) | ~800 MB |
| Whisper модель `small` | ~500 MB |
| **Итого** | **~1.5 GB** |

**Решение:**
- Whisper модель НЕ включать в сборку — скачивать при первом запуске (~500 MB)
- Использовать `torch` CPU-only (без CUDA) — экономит ~1 GB
- PyInstaller `--onedir` (не `--onefile`) — быстрее запуск, меньше RAM

### 2. Аудио-захват — платформозависимый
| Платформа | Микрофон | Системный звук (loopback) |
|-----------|----------|--------------------------|
| Windows | `sounddevice` (PortAudio) | `PyAudioWPatch` (WASAPI Loopback) |
| macOS | `sounddevice` (CoreAudio) | `soundflower` / `BlackHole` (виртуальный аудиодрайвер) |
| Linux | `sounddevice` (PulseAudio/ALSA) | `PulseAudio monitor` (встроенный loopback) |

**Решение:**
- `sounddevice` работает на всех платформах для микрофона
- Для loopback: абстракция `audio/loopback.py` с платформозависимыми реализациями
- macOS: пользователь устанавливает BlackHole (бесплатный), приложение определяет его автоматически
- Linux: PulseAudio monitor работает из коробки

### 3. PyInstaller — платформозависимый
PyInstaller собирает бинарник **только для текущей ОС**. Нельзя собрать .exe на Mac.

**Решение:** CI/CD через GitHub Actions — 3 runner'а (windows, macos, ubuntu).

---

## План реализации

### Этап 1 — PyInstaller spec для бэкенда

**Файл:** `backend/voicescribe.spec`

```python
# voicescribe.spec
a = Analysis(
    ['src/main.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Silero VAD модель (используется faster-whisper)
        ('path/to/silero_vad.onnx', 'silero_vad'),
    ],
    hiddenimports=[
        'faster_whisper',
        'ctranslate2',
        'sounddevice',
        'aiosqlite',
        'pydantic',
        'pydantic_settings',
        'numpy',
        'scipy',
        'sklearn',
        # Платформозависимые:
        'PyAudioWPatch',      # Windows only
    ],
    hookspath=[],
    excludes=[
        'matplotlib', 'PIL', 'tkinter',  # Не используются
        'pyannote',  # Пока не работает, исключаем
    ],
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    name='voicescribe-backend',
    console=False,          # Нет окна консоли
    strip=False,
    upx=True,               # Сжатие
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    name='voicescribe-backend',
)
```

**Задачи:**
- [ ] Создать `voicescribe.spec` с правильными hidden imports
- [ ] Решить проблему с `ctranslate2` (C++ библиотека, нужны binaries)
- [ ] Решить проблему с `torch` (тяжёлый, нужен CPU-only вариант)
- [ ] Протестировать на Windows: `pyinstaller voicescribe.spec`
- [ ] Проверить что `python -m src.main serve` работает из frozen binary

### Этап 2 — Абстракция аудио-захвата для кроссплатформенности

**Текущий стек (Windows only):**
```
audio/capture.py     → PyAudioWPatch (WASAPI)
audio/microphone.py  → sounddevice
```

**Новая структура:**
```
audio/
├── capture.py          → Абстрактный интерфейс AudioCapture
├── microphone.py       → sounddevice (кроссплатформенный, без изменений)
├── loopback/
│   ├── __init__.py     → auto-detect платформы, вернуть нужный класс
│   ├── wasapi.py       → PyAudioWPatch (Windows)
│   ├── pulseaudio.py   → PulseAudio monitor (Linux)
│   └── coreaudio.py    → BlackHole/Soundflower detection (macOS)
└── mixer.py            → Без изменений
```

**Задачи:**
- [ ] Выделить интерфейс `LoopbackCapture(ABC)` с методами `start()`, `stop()`, `get_audio()`
- [ ] Перенести WASAPI-код в `loopback/wasapi.py`
- [ ] Реализовать `loopback/pulseaudio.py` — через `sounddevice` + PulseAudio monitor source
- [ ] Реализовать `loopback/coreaudio.py` — поиск BlackHole/Soundflower virtual device
- [ ] Фабрика в `loopback/__init__.py`: `get_loopback_capture()` → возвращает нужный класс по `sys.platform`
- [ ] Обновить `requirements.txt` — `PyAudioWPatch` только для Windows, добавить `pulsectl` для Linux

### Этап 3 — Интеграция PyInstaller в electron-builder

**Изменения в `electron/main.js` → `getPythonPath()`:**

```javascript
function getPythonPath() {
  const candidates = [];
  const ext = process.platform === 'win32' ? '.exe' : '';

  if (app.isPackaged) {
    // PyInstaller frozen backend внутри resources/
    const frozenBackend = path.join(
      process.resourcesPath, 'backend',
      `voicescribe-backend${ext}`
    );
    candidates.push({
      exe: frozenBackend,
      args: ['serve'],
      cwd: path.join(process.resourcesPath, 'backend'),
    });
  }

  // Dev fallback: Python venv
  const devBackend = path.resolve(__dirname, '..', '..', 'backend');
  candidates.push({
    exe: path.join(devBackend, '.venv',
      process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python'),
    args: ['-m', 'src.main', 'serve'],
    cwd: devBackend,
  });

  // ...
}
```

**Изменения в `package.json` → `build`:**

```json
{
  "build": {
    "extraResources": [
      {
        "from": "../backend/dist/voicescribe-backend",
        "to": "backend"
      }
    ],
    "mac": {
      "target": ["dmg", "zip"],
      "arch": ["x64", "arm64"],
      "category": "public.app-category.productivity"
    },
    "linux": {
      "target": ["AppImage", "deb"],
      "category": "AudioVideo"
    },
    "win": {
      "target": ["nsis", "portable"]
    }
  }
}
```

**Задачи:**
- [ ] Обновить `getPythonPath()` для поиска frozen binary
- [ ] Обновить `package.json` build config для 3 платформ
- [ ] Настроить `extraResources` — копировать PyInstaller output
- [ ] macOS: подписание (можно ad-hoc для тестов)
- [ ] Linux: AppImage + .deb

### Этап 4 — GitHub Actions CI/CD

**Файл:** `.github/workflows/build.yml`

```yaml
name: Build & Release

on:
  push:
    tags: ['v*']

jobs:
  build:
    strategy:
      matrix:
        include:
          - os: windows-latest
            platform: win
            artifact: VoiceScribe-Setup-*.exe
          - os: macos-latest
            platform: mac
            artifact: VoiceScribe-*.dmg
          - os: ubuntu-latest
            platform: linux
            artifact: VoiceScribe-*.AppImage

    runs-on: ${{ matrix.os }}

    steps:
      - uses: actions/checkout@v4

      # Python
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install Python deps
        run: |
          cd backend
          pip install -r requirements.txt
          pip install pyinstaller

      - name: Build backend (PyInstaller)
        run: |
          cd backend
          pyinstaller voicescribe.spec

      # Node.js
      - uses: actions/setup-node@v4
        with:
          node-version: '20'

      - name: Install & build frontend
        run: |
          cd frontend
          npm ci
          npm run build

      - name: Build Electron app
        run: |
          cd frontend
          npx electron-builder --${{ matrix.platform }}

      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: voicescribe-${{ matrix.platform }}
          path: release/*

  release:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
      - name: Create GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          files: |
            voicescribe-win/**
            voicescribe-mac/**
            voicescribe-linux/**
```

**Задачи:**
- [ ] Создать `.github/workflows/build.yml`
- [ ] Настроить GitHub Secrets для подписания (опционально)
- [ ] Тестировать на каждой платформе (CI runner)
- [ ] Добавить auto-release при создании тега `v*`

### Этап 5 — Автоскачивание модели Whisper

При первом запуске модель `small` (~500 MB) нужно скачать. Сейчас `faster-whisper` делает это автоматически в `~/.cache/huggingface/`, но для portable-приложения лучше скачивать в папку приложения.

**Задачи:**
- [ ] При первом запуске показать UI "Downloading model... (461 MB)"
- [ ] Скачивать в `app.getPath('userData')/models/`
- [ ] Передать путь к модели в backend через аргумент: `voicescribe-backend serve --model-dir /path/to/models`
- [ ] Прогресс-бар скачивания в UI
- [ ] Кэш: если модель уже скачана — не скачивать повторно

---

## Порядок работы

```
Этап 1 (PyInstaller)     ████████░░░░  — 1-2 дня
Этап 2 (Кроссплатформа)  ████████████  — 2-3 дня
Этап 3 (electron-builder)████████░░░░  — 1 день
Этап 4 (CI/CD)           ████████████  — 1 день
Этап 5 (Автоскачивание)  ████░░░░░░░░  — 0.5 дня
                                         ─────────
                                         ~5-7 дней
```

## Зависимости по платформам

### Windows
```
# requirements.txt (без изменений)
faster-whisper>=1.1.0
PyAudioWPatch>=0.2.13    # Windows-only loopback
sounddevice>=0.4
torch>=2.1 --index-url https://download.pytorch.org/whl/cpu
# ... остальное
```

### macOS
```
# requirements-mac.txt
faster-whisper>=1.1.0
sounddevice>=0.4          # CoreAudio
torch>=2.1 --index-url https://download.pytorch.org/whl/cpu
# PyAudioWPatch НЕ нужен
# Loopback через BlackHole virtual device + sounddevice
```

### Linux
```
# requirements-linux.txt
faster-whisper>=1.1.0
sounddevice>=0.4          # PulseAudio/ALSA
pulsectl>=23.5            # PulseAudio API для loopback
torch>=2.1 --index-url https://download.pytorch.org/whl/cpu
# PyAudioWPatch НЕ нужен
```

---

## Итоговый UX для пользователя

### Windows
1. Скачать `VoiceScribe-Setup-1.0.0.exe` (~200 MB, без модели)
2. Запустить → установка за 30 сек
3. Первый запуск → "Downloading AI model... 461 MB" → 2-5 мин
4. Готово к работе

### macOS
1. Скачать `VoiceScribe-1.0.0.dmg` (~200 MB)
2. Перетащить в Applications
3. Первый запуск → скачивание модели
4. Для системного звука: установить BlackHole (бесплатно, ссылка в Settings)

### Linux
1. Скачать `VoiceScribe-1.0.0.AppImage` (~200 MB)
2. `chmod +x VoiceScribe-1.0.0.AppImage && ./VoiceScribe-1.0.0.AppImage`
3. Первый запуск → скачивание модели
4. Системный звук работает через PulseAudio (из коробки)

---

## Альтернативный подход: без PyInstaller

Если PyInstaller окажется слишком сложным (проблемы с torch, ctranslate2), альтернатива:

- **Embedded Python** — скачивать Python embeddable package (~15 MB) при установке
- Устанавливать pip + requirements в portable venv
- Electron запускает `python.exe -m src.main serve` как сейчас

Плюс: проще, не нужно бороться с PyInstaller hidden imports.
Минус: первый запуск ~10 мин (установка зависимостей), нужен интернет.
