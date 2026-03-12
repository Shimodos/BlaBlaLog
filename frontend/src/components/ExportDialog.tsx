import { useState } from 'react';
import { useBackend } from '@/hooks/useBackend';
import type { ExportOptions } from '@/types';

interface ExportDialogProps {
  meetingId: string;
  meetingTitle: string;
  onClose: () => void;
}

export function ExportDialog({ meetingId, meetingTitle, onClose }: ExportDialogProps) {
  const { sendCommand } = useBackend();
  const [options, setOptions] = useState<ExportOptions>({
    format: 'md',
    includeTimestamps: true,
    includeSpeakers: true,
  });
  const [preview, setPreview] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [exported, setExported] = useState(false);

  async function handlePreview() {
    setLoading(true);
    try {
      const res = await sendCommand('export', {
        meeting_id: meetingId,
        ...options,
        preview: true,
      });
      if (res?.content) setPreview(res.content);
    } catch {
      setPreview('Failed to generate preview');
    } finally {
      setLoading(false);
    }
  }

  async function handleExport() {
    setLoading(true);
    try {
      await sendCommand('export', {
        meeting_id: meetingId,
        ...options,
      });
      setExported(true);
      setTimeout(() => onClose(), 1200);
    } catch {
      // error handled by backend
    } finally {
      setLoading(false);
    }
  }

  const formatLabels: Record<string, string> = {
    md: 'Markdown (.md)',
    txt: 'Plain Text (.txt)',
    srt: 'Subtitles (.srt)',
    json: 'JSON (.json)',
  };

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} style={{ minWidth: 460 }}>
        <div className="modal__header">
          <h2 className="modal__title">Export Meeting</h2>
          <button className="modal__close" onClick={onClose}>&times;</button>
        </div>

        <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 20 }}>
          {meetingTitle}
        </div>

        {exported ? (
          <div style={{ textAlign: 'center', padding: 30, color: 'var(--success)', fontSize: 15, fontWeight: 600 }}>
            Exported successfully!
          </div>
        ) : (
          <>
            <div className="form-group">
              <label className="form-label">Format</label>
              <select
                className="form-select"
                value={options.format}
                onChange={(e) => {
                  setOptions({ ...options, format: e.target.value as ExportOptions['format'] });
                  setPreview(null);
                }}
              >
                {Object.entries(formatLabels).map(([val, label]) => (
                  <option key={val} value={val}>{label}</option>
                ))}
              </select>
            </div>

            <div className="form-group flex gap-16">
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={options.includeTimestamps}
                  onChange={(e) => {
                    setOptions({ ...options, includeTimestamps: e.target.checked });
                    setPreview(null);
                  }}
                />
                Include timestamps
              </label>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={options.includeSpeakers}
                  onChange={(e) => {
                    setOptions({ ...options, includeSpeakers: e.target.checked });
                    setPreview(null);
                  }}
                />
                Include speakers
              </label>
            </div>

            {preview && (
              <div className="form-group">
                <label className="form-label">Preview</label>
                <div className="preview-box">{preview}</div>
              </div>
            )}

            <div className="modal__actions">
              <button className="btn btn--ghost" onClick={handlePreview} disabled={loading}>
                {loading && !preview ? 'Loading...' : 'Preview'}
              </button>
              <button className="btn btn--primary" onClick={handleExport} disabled={loading}>
                {loading ? 'Exporting...' : 'Export'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
