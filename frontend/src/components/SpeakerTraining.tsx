import { useState, useRef, useCallback, useEffect } from 'react';
import { useBackend } from '@/hooks/useBackend';
import { useAppStore } from '@/stores/appStore';

interface SpeakerTrainingProps {
  onClose: () => void;
  onSaved: () => void;
}

export function SpeakerTraining({ onClose, onSaved }: SpeakerTrainingProps) {
  const { sendCommand } = useBackend();
  const { setError } = useAppStore();

  const [name, setName] = useState('');
  const [isRecording, setIsRecording] = useState(false);
  const [duration, setDuration] = useState(0);
  const [audioPath, setAudioPath] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const handleStartRecording = useCallback(async () => {
    setDuration(0);
    setAudioPath(null);
    try {
      await sendCommand('start_speaker_recording');
      setIsRecording(true);
      const start = Date.now();
      timerRef.current = setInterval(() => {
        setDuration(Math.floor((Date.now() - start) / 1000));
      }, 1000);
    } catch (err: any) {
      setError(err?.message || 'Failed to start recording');
    }
  }, [sendCommand, setError]);

  const handleStopRecording = useCallback(async () => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    setIsRecording(false);
    try {
      const res = await sendCommand('stop_speaker_recording');
      if (res?.audio_path) setAudioPath(res.audio_path);
    } catch (err: any) {
      setError(err?.message || 'Failed to stop recording');
    }
  }, [sendCommand, setError]);

  const handleSave = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      await sendCommand('create_speaker_profile', {
        name: name.trim(),
      });
      onSaved();
    } catch (err: any) {
      setError(err?.message || 'Failed to save speaker');
    } finally {
      setSaving(false);
    }
  };

  const canSave = name.trim().length > 0 && (audioPath || duration >= 10);

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal__header">
          <h2 className="modal__title">Train New Speaker</h2>
          <button className="modal__close" onClick={onClose}>&times;</button>
        </div>

        <div className="form-group">
          <label className="form-label">Speaker Name</label>
          <input
            className="form-input"
            placeholder="e.g. John Doe"
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
          />
        </div>

        <div className="form-group">
          <label className="form-label">Voice Sample</label>
          <div className="speaker-training__record-area">
            <div className="speaker-training__timer" style={isRecording ? { color: 'var(--danger)' } : {}}>
              {Math.floor(duration / 60).toString().padStart(2, '0')}:
              {(duration % 60).toString().padStart(2, '0')}
            </div>

            {isRecording ? (
              <button className="btn btn--danger" onClick={handleStopRecording}>
                Stop Recording
              </button>
            ) : (
              <button className="btn btn--primary" onClick={handleStartRecording}>
                {audioPath ? 'Re-record' : 'Start Recording'}
              </button>
            )}

            <div className="speaker-training__hint">
              Record 10-30 seconds of the speaker's voice for best results.
              {audioPath && !isRecording && (
                <span style={{ color: 'var(--success)', display: 'block', marginTop: 4 }}>
                  Recording captured ({duration}s)
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="modal__actions">
          <button className="btn btn--ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn--primary" onClick={handleSave} disabled={!canSave || saving}>
            {saving ? 'Saving...' : 'Save Speaker'}
          </button>
        </div>
      </div>
    </div>
  );
}
