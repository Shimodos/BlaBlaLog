import { useEffect, useState } from 'react';
import { useAppStore } from '@/stores/appStore';
import { useBackend } from '@/hooks/useBackend';
import type { Meeting } from '@/types';

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString('en-US', {
    month: 'short',
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

export function MeetingHistory() {
  const { meetings, setMeetings, setPage, setSelectedMeetingId, setError } = useAppStore();
  const { sendCommand } = useBackend();
  const [loading, setLoading] = useState(true);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  useEffect(() => {
    loadMeetings();
  }, []);

  async function loadMeetings() {
    setLoading(true);
    try {
      const res = await sendCommand('list_meetings');
      if (Array.isArray(res)) setMeetings(res);
    } catch (err: any) {
      setError(err?.message || 'Failed to load meetings');
    } finally {
      setLoading(false);
    }
  }

  function handleOpenMeeting(id: string) {
    setSelectedMeetingId(id);
    setPage('meeting-detail');
  }

  async function handleDelete(id: string) {
    try {
      await sendCommand('delete_meeting', { meeting_id: id });
      setMeetings(meetings.filter((m) => m.id !== id));
    } catch (err: any) {
      setError(err?.message || 'Failed to delete meeting');
    }
    setDeleteTarget(null);
  }

  if (loading) {
    return (
      <div className="page page-enter">
        <div className="loading-center">
          <div className="spinner" />
          Loading meetings...
        </div>
      </div>
    );
  }

  return (
    <div className="page page-enter">
      <div className="page-header">
        <h1 className="page-title">Meeting History</h1>
        <button className="btn btn--ghost btn--sm" onClick={loadMeetings}>
          Refresh
        </button>
      </div>

      {meetings.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state__icon">&#128196;</div>
          <div className="empty-state__text">
            No meetings recorded yet. Start a new recording to get going.
          </div>
        </div>
      ) : (
        <div className="table-wrap card" style={{ padding: 0 }}>
          <table>
            <thead>
              <tr>
                <th>Title</th>
                <th>Date</th>
                <th>Duration</th>
                <th>Language</th>
                <th style={{ width: 60 }}></th>
              </tr>
            </thead>
            <tbody>
              {meetings.map((m: Meeting) => (
                <tr key={m.id} className="clickable" onClick={() => handleOpenMeeting(m.id)}>
                  <td style={{ color: 'var(--text-primary)', fontWeight: 500 }}>
                    {m.title || 'Untitled Meeting'}
                  </td>
                  <td>{formatDate(m.started_at)}</td>
                  <td>{formatDuration(m.duration_seconds)}</td>
                  <td>
                    <span className="badge badge--accent">
                      {m.language?.toUpperCase() || 'AUTO'}
                    </span>
                  </td>
                  <td>
                    <button
                      className="btn btn--ghost btn--icon"
                      title="Delete"
                      onClick={(e) => {
                        e.stopPropagation();
                        setDeleteTarget(m.id);
                      }}
                      style={{ color: 'var(--text-muted)' }}
                    >
                      &#128465;
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Delete confirmation */}
      {deleteTarget && (
        <div className="overlay" onClick={() => setDeleteTarget(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal__header">
              <h2 className="modal__title">Delete Meeting</h2>
              <button className="modal__close" onClick={() => setDeleteTarget(null)}>
                &times;
              </button>
            </div>
            <p className="confirm-text">
              Are you sure you want to delete this meeting? This action cannot be undone.
            </p>
            <div className="modal__actions">
              <button className="btn btn--ghost" onClick={() => setDeleteTarget(null)}>
                Cancel
              </button>
              <button className="btn btn--danger" onClick={() => handleDelete(deleteTarget)}>
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
