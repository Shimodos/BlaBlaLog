# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for VoiceScribe backend (cross-platform).

Usage:
    cd backend
    pyinstaller voicescribe.spec

Output: dist/voicescribe-backend/ (one-directory mode)

The resulting folder is copied into frontend/resources/backend/
by the build script, and electron-builder bundles it as an extraResource.
"""

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Collect data files required by ML packages
datas = []
datas += collect_data_files("silero_vad")
datas += collect_data_files("faster_whisper")

# Hidden imports: packages that are imported dynamically or by ML frameworks
hiddenimports = [
    # Core ML
    "faster_whisper",
    "torch",
    "torchaudio",
    "numpy",
    # Audio — cross-platform
    "sounddevice",
    # Audio loopback — all platform modules included, runtime picks the right one
    "src.audio.loopback",
    "src.audio.loopback.base",
    "src.audio.loopback.wasapi",
    "src.audio.loopback.pulseaudio",
    "src.audio.loopback.coreaudio",
    # VAD
    "silero_vad",
    # Speaker diarization
    "speechbrain",
    "sklearn",
    "sklearn.cluster",
    "sklearn.utils",
    # Async / storage
    "aiosqlite",
    "pydantic",
    "pydantic_settings",
    # Stdlib that PyInstaller sometimes misses
    "wave",
    "json",
    "asyncio",
    "argparse",
    "uuid",
    "signal",
]

# Platform-specific hidden imports
if sys.platform == "win32":
    hiddenimports += ["PyAudioWPatch", "pyaudiowpatch"]

# Pull in all submodules for packages that load things lazily
hiddenimports += collect_submodules("faster_whisper")
hiddenimports += collect_submodules("silero_vad")

a = Analysis(
    ["src/main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "tkinter",
        "PIL",
        "IPython",
        "jupyter",
        "notebook",
        "pyannote",  # Not working yet, exclude to save space
    ],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="voicescribe-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # Console app — Electron reads stdout/stderr
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="voicescribe-backend",
)
