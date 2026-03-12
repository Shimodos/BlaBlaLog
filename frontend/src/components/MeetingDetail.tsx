import { useEffect, useState, useRef } from 'react';
import { useAppStore } from '@/stores/appStore';
import { useBackend } from '@/hooks/useBackend';
import { LiveTranscript } from './LiveTranscript';
import { ExportDialog } from './ExportDialog';
import type { Meeting, TranscriptSegment } from '@/types';

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m < 60) return `${m}m ${s}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

export function MeetingDetail() {
  const { selectedMeetingId, setPage, setError } = useAppStore();
  const { sendCommand } = useBackend();

  const [meeting, setMeeting] = useState<Meeting | null>(null);
  const [segments, setSegments] = useState<TranscriptSegment[]>([]);
  const [loading, setLoading] = useState(true);
  const [showExport, setShowExport] = useState(false);
  const [title, setTitle] = useState('');
  const titleTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!selectedMeetingId) {
      setPage('history');
      return;
    }

    async function load() {
      setLoading(true);
      try {
        const [meetingRes, segmentsRes] = await Promise.all([
          sendCommand('get_meeting', { meeting_id: selectedMeetingId }),
          sendCommand('get_transcript', { meeting_id: selectedMeetingId }),
        ]);
        if (meetingRes && meetingRes.id) {
          setMeeting(meetingRes);
          setTitle(meetingRes.title || 'Untitled Meeting');
        }
        if (Array.isArray(segmentsRes)) setSegments(segmentsRes);
      } catch (err: any) {
        setError(err?.message || 'Failed to load meeting');
      } finally {
        setLoading(false);
      }
    }

    load();
  }, [selectedMeetingId, sendCommand, setPage, setError]);

  function handleTitleChange(newTitle: string) {
    setTitle(newTitle);
    if (titleTimeout.current) clearTimeout(titleTimeout.current);
    titleTimeout.current = setTimeout(() => {
      sendCommand('update_meeting', {
        meeting_id: selectedMeetingId,
        title: newTitle,
      }).catch(() => {});
    }, 800);
  }

  if (loading) {
    return (
      <div className="page page-enter">
        <div className="loading-center">
          <div className="spinner" />
          Loading meeting...
        </div>
      </div>
    );
  }

  if (!meeting) {
    return (
      <div className="page page-enter">
        <div className="empty-state">
          <div className="empty-state__text">Meeting not found.</div>
          <button className="btn btn--ghost" onClick={() => setPage('history')}>
            Back to History
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="page page-enter" style={{ display: 'flex', flexDirection: 'column' }}>
      <div style={{ marginBottom: 16 }}>
        <button
          className="btn btn--ghost btn--sm"
          onClick={() => setPage('history')}
          style={{ marginBottom: 12 }}
        >
          &larr; Back to History
        </button>

        <div className="flex items-center justify-between">
          <input
            className="editable-title"
            value={title}
            onChange={(e) => handleTitleChange(e.target.value)}
            spellCheck={false}
          />
          <button className="btn btn--primary btn--sm" onClick={() => setShowExport(true)}>
            Export
          </button>
        </div>

        <div className="meeting-meta">
          <div className="meeting-meta__item">
            <span>&#128197;</span>
            {formatDate(meeting.started_at)}
          </div>
          <div className="meeting-meta__item">
            <span>&#9201;</span>
            {formatDuration(meeting.duration_seconds)}
          </div>
          <div className="meeting-meta__item">
            <span className="badge badge--accent">
              {meeting.language?.toUpperCase() || 'AUTO'}
            </span>
          </div>
        </div>
      </div>

      <div className="card" style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 }}>
          Transcript
        </div>
        <LiveTranscript segments={segments} />
      </div>

      {showExport && (
        <ExportDialog
          meetingId={meeting.id}
          meetingTitle={title}
          onClose={() => setShowExport(false)}
        />
      )}
    </div>
  );
}
