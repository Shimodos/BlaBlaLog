import { useEffect, useState } from 'react';
import { useAppStore } from '@/stores/appStore';
import { useBackend } from '@/hooks/useBackend';
import { SpeakerTraining } from './SpeakerTraining';
import type { Speaker } from '@/types';

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

export function SpeakerList() {
  const { speakers, setSpeakers, setError } = useAppStore();
  const { sendCommand } = useBackend();

  const [loading, setLoading] = useState(true);
  const [showTraining, setShowTraining] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  useEffect(() => {
    loadSpeakers();
  }, []);

  async function loadSpeakers() {
    setLoading(true);
    try {
      const res = await sendCommand('list_speakers');
      if (Array.isArray(res)) setSpeakers(res);
    } catch (err: any) {
      setError(err?.message || 'Failed to load speakers');
    } finally {
      setLoading(false);
    }
  }

  async function handleDelete(id: string) {
    try {
      await sendCommand('delete_speaker', { speaker_id: id });
      setSpeakers(speakers.filter((s) => s.id !== id));
    } catch (err: any) {
      setError(err?.message || 'Failed to delete speaker');
    }
    setDeleteTarget(null);
  }

  function handleTrainingSaved() {
    setShowTraining(false);
    loadSpeakers();
  }

  if (loading) {
    return (
      <div className="page page-enter">
        <div className="loading-center">
          <div className="spinner" />
          Loading speakers...
        </div>
      </div>
    );
  }

  return (
    <div className="page page-enter">
      <div className="page-header">
        <h1 className="page-title">Speaker Profiles</h1>
        <button className="btn btn--primary btn--sm" onClick={() => setShowTraining(true)}>
          + Train New Speaker
        </button>
      </div>

      {speakers.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state__icon">&#128100;</div>
          <div className="empty-state__text">
            No speaker profiles yet. Train a speaker to enable voice identification.
          </div>
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 12 }}>
          {speakers.map((sp: Speaker) => (
            <div key={sp.id} className="card flex items-center justify-between">
              <div className="flex items-center gap-12">
                <div
                  style={{
                    width: 40,
                    height: 40,
                    borderRadius: '50%',
                    background: 'var(--accent-light)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: 16,
                    fontWeight: 700,
                    color: 'var(--accent)',
                  }}
                >
                  {sp.name.charAt(0).toUpperCase()}
                </div>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>{sp.name}</div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    Added {formatDate(sp.created_at)}
                  </div>
                </div>
              </div>
              <button
                className="btn btn--ghost btn--icon"
                title="Delete"
                onClick={() => setDeleteTarget(sp.id)}
                style={{ color: 'var(--text-muted)' }}
              >
                &#128465;
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Training dialog */}
      {showTraining && (
        <SpeakerTraining
          onClose={() => setShowTraining(false)}
          onSaved={handleTrainingSaved}
        />
      )}

      {/* Delete confirmation */}
      {deleteTarget && (
        <div className="overlay" onClick={() => setDeleteTarget(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal__header">
              <h2 className="modal__title">Delete Speaker</h2>
              <button className="modal__close" onClick={() => setDeleteTarget(null)}>
                &times;
              </button>
            </div>
            <p className="confirm-text">
              Are you sure you want to delete this speaker profile? The speaker will no longer be
              identified in future recordings.
            </p>
            <div className="modal__actions">
              <button className="btn btn--ghost" onClick={() => setDeleteTarget(null)}>Cancel</button>
              <button className="btn btn--danger" onClick={() => handleDelete(deleteTarget)}>Delete</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
