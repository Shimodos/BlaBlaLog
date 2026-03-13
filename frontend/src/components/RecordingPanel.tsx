import { useEffect, useRef, useState } from 'react';
import { useAppStore } from '@/stores/appStore';
import { useBackend } from '@/hooks/useBackend';
import { LiveTranscript } from './LiveTranscript';
import type { AudioDevice, TranscriptSegment } from '@/types';

function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) {
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  }
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

function VuMeter({ level, label }: { level: number; label: string }) {
  const bars = 20;
  const activeBars = Math.round(level * bars);
  return (
    <div className="vu-meter">
      <span className="vu-meter__label">{label}</span>
      <div className="vu-meter__bars">
        {Array.from({ length: bars }, (_, i) => (
          <div
            key={i}
            className={`vu-meter__bar${i < activeBars ? ' vu-meter__bar--active' : ''}${i >= bars * 0.8 ? ' vu-meter__bar--hot' : ''}`}
          />
        ))}
      </div>
    </div>
  );
}

function ProcessingProgress({ stage, progress, message }: { stage: string; progress: number; message: string }) {
  const isActive = stage === 'transcription' || stage === 'diarization' || stage === 'identification';
  return (
    <div className="processing-progress">
      <div className="processing-progress__header">
        <span className="processing-progress__stage">
          {isActive && <span className="processing-spinner" />}
          {stage === 'transcription' && 'Transcribing...'}
          {stage === 'diarization' && 'Speaker diarization...'}
          {stage === 'identification' && 'Identifying speakers...'}
          {stage === 'complete' && 'Done!'}
          {stage === 'error' && 'Error'}
        </span>
        <span className="processing-progress__percent">{progress}%</span>
      </div>
      <div className="processing-progress__track">
        <div
          className={`processing-progress__fill${stage === 'error' ? ' processing-progress__fill--error' : ''}${stage === 'complete' ? ' processing-progress__fill--complete' : ''}${isActive ? ' processing-progress__fill--pulse' : ''}`}
          style={{ width: `${Math.max(progress, isActive ? 5 : 0)}%` }}
        />
      </div>
      <div className="processing-progress__message">{message}</div>
    </div>
  );
}

export function RecordingPanel() {
  const {
    isRecording,
    recordingDuration,
    recordingStartTime,
    liveSegments,
    audioLevels,
    processing,
    setRecording,
    setRecordingDuration,
    setRecordingStartTime,
    setCurrentMeetingId,
    setAudioLevels,
    setProcessing,
    upsertLiveSegment,
    clearLiveSegments,
    setError,
  } = useAppStore();

  const { sendCommand, subscribe } = useBackend();
  const [micDevices, setMicDevices] = useState<AudioDevice[]>([]);
  const [loopbackDevices, setLoopbackDevices] = useState<AudioDevice[]>([]);
  const [selectedMic, setSelectedMic] = useState('');
  const [selectedLoopback, setSelectedLoopback] = useState('');
  const [loading, setLoading] = useState(false);

  // Keep timer running while recording — uses store so survives tab switches
  useEffect(() => {
    if (!isRecording || !recordingStartTime) return;

    const id = setInterval(() => {
      setRecordingDuration(Math.floor((Date.now() - recordingStartTime) / 1000));
    }, 500);

    return () => clearInterval(id);
  }, [isRecording, recordingStartTime, setRecordingDuration]);

  // Load devices on mount
  useEffect(() => {
    // Load microphone devices
    sendCommand('get_input_devices').then((res) => {
      const raw = Array.isArray(res) ? res : [];
      const mapped: AudioDevice[] = raw.map((d: any) => ({
        id: String(d.index ?? d.id ?? ''),
        name: d.name || `Device ${d.index}`,
        isDefault: !!d.isDefault || !!d.is_default,
      }));
      setMicDevices(mapped);
      if (mapped.length > 0) {
        const def = mapped.find((d) => d.isDefault) || mapped[0];
        setSelectedMic(def.id);
      }
    }).catch(() => {});

    // Load loopback (system audio) devices
    sendCommand('get_loopback_devices').then((res) => {
      const raw = Array.isArray(res) ? res : [];
      const mapped: AudioDevice[] = raw.map((d: any) => ({
        id: String(d.index ?? d.id ?? ''),
        name: d.name || `Loopback ${d.index}`,
        isDefault: false,
      }));
      setLoopbackDevices(mapped);
      if (mapped.length > 0) {
        setSelectedLoopback(mapped[0].id);
      }
    }).catch(() => {});
  }, [sendCommand]);

  // Subscribe to backend events
  useEffect(() => {
    const unsub = subscribe((event: any) => {
      const method = event.method;
      const params = event.params;

      // VU meter levels
      if (method === 'audio.levels' && params) {
        setAudioLevels({
          mic: params.mic ?? 0,
          loopback: params.loopback ?? 0,
        });
      }

      // Processing progress
      if (method === 'processing.status' && params) {
        if (params.stage === 'complete') {
          setProcessing({
            isProcessing: false,
            stage: 'complete',
            progress: 100,
            message: params.message || 'Done!',
          });

          // Load completed segments into live transcript
          if (params.segments && Array.isArray(params.segments)) {
            clearLiveSegments();
            for (const seg of params.segments) {
              upsertLiveSegment({
                id: seg.id || Date.now(),
                meeting_id: seg.meeting_id || '',
                speaker_id: seg.speaker_id || null,
                speaker_label: seg.speaker_label || 'Speaker',
                start_time: seg.start_time || 0,
                end_time: seg.end_time || 0,
                text: seg.text || '',
                confidence: seg.confidence || 0,
              });
            }
          }
        } else if (params.stage === 'error') {
          setProcessing({
            isProcessing: false,
            stage: 'error',
            progress: 0,
            message: params.message || 'Error',
          });
        } else {
          setProcessing({
            isProcessing: true,
            stage: params.stage || '',
            progress: params.progress ?? 0,
            message: params.message || '',
          });
        }
      }
    });

    return unsub;
  }, [subscribe, setAudioLevels, setProcessing, upsertLiveSegment, clearLiveSegments]);

  // Polling fallback: if processing is stuck, poll for transcript
  const processingMeetingIdRef = useRef<string | null>(null);
  useEffect(() => {
    if (!processing.isProcessing) {
      processingMeetingIdRef.current = null;
      return;
    }

    // Remember which meeting we're processing
    const meetingId = useAppStore.getState().currentMeetingId || processingMeetingIdRef.current;
    processingMeetingIdRef.current = meetingId;
    if (!meetingId) return;

    // Poll every 3 seconds
    const pollInterval = setInterval(async () => {
      try {
        const status = await sendCommand('get_status');
        // If backend is idle → processing finished, fetch transcript
        if (status?.state === 'idle') {
          const segments = await sendCommand('get_transcript', { meeting_id: meetingId });
          if (Array.isArray(segments) && segments.length > 0) {
            clearLiveSegments();
            for (const seg of segments) {
              upsertLiveSegment({
                id: seg.id || Date.now(),
                meeting_id: seg.meeting_id || meetingId,
                speaker_id: seg.speaker_id || null,
                speaker_label: seg.speaker_label || 'Speaker',
                start_time: seg.start_time || 0,
                end_time: seg.end_time || 0,
                text: seg.text || '',
                confidence: seg.confidence || 0,
              });
            }
            setProcessing({
              isProcessing: false,
              stage: 'complete',
              progress: 100,
              message: `Done! ${segments.length} segments`,
            });
          }
        }
      } catch {
        // Ignore poll errors
      }
    }, 3000);

    return () => clearInterval(pollInterval);
  }, [processing.isProcessing, sendCommand, setProcessing, upsertLiveSegment, clearLiveSegments]);

  const handleStartRecording = async () => {
    setLoading(true);
    setError(null);
    clearLiveSegments();
    setRecordingDuration(0);
    setProcessing({ isProcessing: false, stage: '', progress: 0, message: '' });
    setAudioLevels({ mic: 0, loopback: 0 });

    try {
      const res = await sendCommand('start_recording', {
        loopback_device_index: selectedLoopback ? parseInt(selectedLoopback, 10) : undefined,
        mic_device_index: selectedMic ? parseInt(selectedMic, 10) : undefined,
      });

      if (res?.meeting_id) {
        setCurrentMeetingId(res.meeting_id);
      }

      setRecordingStartTime(Date.now());
      setRecording(true);
    } catch (err: any) {
      setError(err?.message || 'Failed to start recording');
    } finally {
      setLoading(false);
    }
  };

  const handleStopRecording = async () => {
    setLoading(true);
    setRecording(false);
    setRecordingStartTime(null);

    try {
      setProcessing({
        isProcessing: true,
        stage: 'transcription',
        progress: 0,
        message: 'Stopping recording, starting transcription...',
      });

      const stopRes = await sendCommand('stop_recording');
      // Keep meeting_id for polling fallback
      processingMeetingIdRef.current = stopRes?.meeting_id || useAppStore.getState().currentMeetingId;
      setCurrentMeetingId(null);
    } catch (err: any) {
      setError(err?.message || 'Failed to stop recording');
      setProcessing({ isProcessing: false, stage: 'error', progress: 0, message: '' });
    } finally {
      setLoading(false);
    }
  };

  const showVuMeter = isRecording;
  const showProcessing = processing.isProcessing || processing.stage === 'complete' || processing.stage === 'error';
  const showTranscript = !isRecording && processing.stage === 'complete' && liveSegments.length > 0;

  return (
    <div className="recording-panel page-enter">
      <div className="recording-panel__controls">
        <div className={`timer${isRecording ? ' timer--recording' : ''}`}>
          {formatDuration(recordingDuration)}
        </div>

        <button
          className={`btn-record${isRecording ? ' btn-record--active' : ''}`}
          onClick={isRecording ? handleStopRecording : handleStartRecording}
          disabled={loading || processing.isProcessing}
          title={isRecording ? 'Stop Recording' : 'Start Recording'}
        >
          {loading ? (
            <div className="spinner" />
          ) : (
            <div className="btn-record__inner" />
          )}
        </button>

        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          {isRecording ? 'Click to stop' : processing.isProcessing ? 'Processing...' : 'Click to start recording'}
        </div>

        {/* Device selectors — two columns */}
        <div className="recording-panel__devices">
          <div className="recording-panel__device">
            <label className="form-label">Microphone</label>
            <select
              className="form-select"
              value={selectedMic}
              onChange={(e) => setSelectedMic(e.target.value)}
              disabled={isRecording || processing.isProcessing}
            >
              {micDevices.length === 0 && (
                <option value="">No microphones found</option>
              )}
              {micDevices.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}{d.isDefault ? ' (Default)' : ''}
                </option>
              ))}
            </select>
          </div>

          <div className="recording-panel__device">
            <label className="form-label">System Audio (Loopback)</label>
            <select
              className="form-select"
              value={selectedLoopback}
              onChange={(e) => setSelectedLoopback(e.target.value)}
              disabled={isRecording || processing.isProcessing}
            >
              {loopbackDevices.length === 0 && (
                <option value="">No loopback devices</option>
              )}
              {loopbackDevices.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* VU Meters — visible during recording */}
      {showVuMeter && (
        <div className="recording-panel__vu card">
          <VuMeter level={audioLevels.mic} label="MIC" />
          <VuMeter level={audioLevels.loopback} label="SYS" />
        </div>
      )}

      {/* Processing progress — visible after stop */}
      {showProcessing && !isRecording && (
        <div className="recording-panel__processing card">
          <ProcessingProgress
            stage={processing.stage}
            progress={processing.progress}
            message={processing.message}
          />
        </div>
      )}

      {/* Transcript — shown after processing completes */}
      {showTranscript && (
        <div className="recording-panel__transcript card" style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 }}>
            Transcript ({liveSegments.length} segments)
          </div>
          <LiveTranscript
            segments={liveSegments}
            partialSegmentId={null}
          />
        </div>
      )}
    </div>
  );
}
