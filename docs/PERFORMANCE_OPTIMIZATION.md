# VoiceScribe Performance Optimization Plan

## Problem

Transcription after recording is slow (especially on CPU-only machines with 16GB RAM).
Apps like Wispr Flow achieve near-instant transcription — but they use **cloud GPU servers** (TensorRT-LLM on AWS). We're running locally, so we need different strategies.

## Current Pipeline Analysis

```
Recording stops
  -> Retrieve full audio from ring buffer
  -> Save WAV file
  -> VAD (Silero) splits audio into speech segments
  -> For EACH segment: call faster-whisper (sequential)
  -> For EACH segment: extract ECAPA-TDNN embedding (sequential)
  -> Greedy speaker clustering
  -> Merge adjacent segments
  -> Save to DB
  -> Send result to frontend
```

### Identified Bottlenecks

| # | Bottleneck | Impact | Current Behavior |
|---|-----------|--------|-----------------|
| 1 | **Model size "small" on CPU** | HIGH | ~6x realtime. 30s audio = ~5s processing |
| 2 | **Double VAD** | MEDIUM | VAD runs externally, then `vad_filter=True` runs it again inside Whisper |
| 3 | **Sequential segment transcription** | MEDIUM | 20 segments = 20 separate Whisper calls with model overhead each time |
| 4 | **No streaming transcription** | HIGH | User waits for ALL processing after stop. No partial results during recording |
| 5 | **Speaker embedding per segment** | LOW-MED | ECAPA-TDNN extraction for every segment, even short ones |
| 6 | **condition_on_previous_text=True** | LOW | Slower decoding, can cause hallucination loops |
| 7 | **Timestamps enabled by default** | LOW | Whisper generates timestamp tokens, adding ~10% decode time |

## Optimization Plan

### Phase 1: Quick Wins (no architecture changes)

**Expected improvement: 2-4x faster transcription**

#### 1.1 — Switch default model to `base` for CPU, keep `small` for GPU
- `base` model: ~16x realtime on CPU (vs ~6x for `small`)
- Quality is sufficient for meetings (especially English/Russian)
- Add `tiny` option for "instant" mode
- Add `distil-small.en` for English-only fast mode
- **File**: `src/utils/config.py`

#### 1.2 — Disable double VAD
- We already run Silero VAD to split audio into segments
- Pass `vad_filter=False` to `engine.transcribe()` to skip redundant second VAD
- **File**: `src/ipc.py` (_batch_process), `src/transcription/engine.py`

#### 1.3 — Optimize Whisper parameters
- Set `condition_on_previous_text=False` (prevents hallucination cascading, faster)
- Set `without_timestamps=True` (skip timestamp token generation)
- Set `no_speech_threshold=0.6` (skip silence segments faster)
- **File**: `src/transcription/engine.py`

#### 1.4 — Batch short segments together
- Instead of 20 separate Whisper calls, concatenate adjacent short segments (< 5s) into 15-30s chunks
- Single Whisper call per chunk = less model overhead
- Map output timing back to original segments
- **File**: `src/ipc.py` (_batch_process)

#### 1.5 — Set CPU thread count
- Pass `cpu_threads=<physical_cores>` when loading faster-whisper model
- Also set `num_workers=2` for parallel segment processing
- **File**: `src/transcription/engine.py`

### ~~Phase 2: Streaming Transcription~~ (deferred — not needed now)

### Phase 2: Model Management & Smart Defaults

#### 2.1 — Auto-detect hardware and pick optimal model
```
GPU detected (CUDA)    -> default: small, compute: float16
CPU with 16GB+ RAM     -> default: base, compute: int8
CPU with 8GB RAM       -> default: tiny, compute: int8
```
- **File**: `src/transcription/engine.py`, `src/utils/config.py`

#### 2.2 — Add "Speed vs Quality" preset in Settings
- Fast: `tiny` model, no speaker clustering, no timestamps
- Balanced: `base` model, basic clustering
- Quality: `small`/`medium` model, full diarization
- **Files**: `src/utils/config.py`, `frontend/src/components/Settings.tsx`

#### 2.3 — Model preloading on app startup
- Currently model loads on first transcription (cold start)
- Load model in background when app starts
- Show "Model loaded" in init modal
- **File**: `src/ipc.py`

### Phase 3: Speaker Processing Optimization

#### 3.1 — Parallel speaker embedding extraction
- Extract embeddings concurrently with transcription
- Use asyncio.gather or ThreadPoolExecutor
- **File**: `src/ipc.py` (_cluster_speakers)

#### 3.2 — Skip clustering for dual-source mode
- When mic + loopback are both captured, speakers are already separated by source
- No need to run ECAPA-TDNN embedding extraction at all
- Currently partially implemented, ensure it's consistent
- **File**: `src/ipc.py` (_batch_process)

#### 3.3 — Cache speaker embeddings
- Don't re-extract embedding for same audio segment
- Store embeddings alongside segments in DB
- **File**: `src/speakers/embeddings.py`, `src/storage/`

## Performance Targets

| Scenario | Before | After Phase 1 |
|----------|--------|--------------|
| 1 min recording, CPU | ~15-20s wait | ~4-6s wait |
| 5 min recording, CPU | ~60-90s wait | ~15-25s wait |
| 1 min recording, GPU | ~3-5s wait | ~1-2s wait |

## Status

### Done (Phase 1):
- [x] **1.1** — Default model `base` for CPU (was `small`)
- [x] **1.2** — Disabled double VAD (`vad_filter=False` in batch)
- [x] **1.3** — Optimized Whisper params (`condition_on_previous_text=False`, `without_timestamps=True`, `no_speech_threshold=0.6`)
- [x] **1.5** — CPU thread count set to physical cores, `num_workers=2`
- [x] Default language changed to `auto` (auto-detect)

### TODO:
- [ ] **1.4** — Batch short segments together (moderate code change)
- [ ] **2.1-2.3** — Smart defaults, presets, model preloading
- [ ] **3.1-3.3** — Speaker processing optimization

## References

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — CTranslate2 Whisper
- [distil-whisper](https://github.com/huggingface/distil-whisper) — 6x faster, ~1% accuracy loss
- [whisper_streaming](https://github.com/ufal/whisper_streaming) — real-time streaming
- [Silero VAD](https://github.com/snakers4/silero-vad) — voice activity detection
- [Wispr Flow architecture](https://www.baseten.co/resources/customers/wispr-flow/) — cloud reference
