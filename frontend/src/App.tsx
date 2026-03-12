import { useAppStore } from '@/stores/appStore';
import { useBackend } from '@/hooks/useBackend';
import { RecordingPanel } from '@/components/RecordingPanel';
import { MeetingHistory } from '@/components/MeetingHistory';
import { MeetingDetail } from '@/components/MeetingDetail';
import { SpeakerList } from '@/components/SpeakerList';
import { Settings } from '@/components/Settings';
import { LogViewer } from '@/components/LogViewer';
import type { PageName } from '@/types';

const NAV_ITEMS: { page: PageName; icon: string; label: string }[] = [
  { page: 'recording', icon: '\u{1F3A4}', label: 'Recording' },
  { page: 'history', icon: '\u{1F4CB}', label: 'History' },
  { page: 'speakers', icon: '\u{1F465}', label: 'Speakers' },
  { page: 'settings', icon: '\u{2699}\uFE0F', label: 'Settings' },
  { page: 'logs', icon: '\u{1F4DC}', label: 'Logs' },
];

function PageContent() {
  const currentPage = useAppStore((s) => s.currentPage);

  switch (currentPage) {
    case 'recording':
      return <RecordingPanel />;
    case 'history':
      return <MeetingHistory />;
    case 'meeting-detail':
      return <MeetingDetail />;
    case 'speakers':
      return <SpeakerList />;
    case 'settings':
      return <Settings />;
    case 'logs':
      return <LogViewer />;
    default:
      return <RecordingPanel />;
  }
}

function WindowControls() {
  const handleMinimize = () => window.electronAPI?.minimize();
  const handleMaximize = () => (window.electronAPI as any)?.maximize?.();
  const handleClose = () => window.electronAPI?.close();

  return (
    <div className="window-controls">
      <button className="window-controls__btn" onClick={handleMinimize} title="Minimize">
        <svg width="10" height="1" viewBox="0 0 10 1"><rect width="10" height="1" fill="currentColor" /></svg>
      </button>
      <button className="window-controls__btn" onClick={handleMaximize} title="Maximize">
        <svg width="10" height="10" viewBox="0 0 10 10"><rect x="0.5" y="0.5" width="9" height="9" fill="none" stroke="currentColor" strokeWidth="1" /></svg>
      </button>
      <button className="window-controls__btn window-controls__btn--close" onClick={handleClose} title="Close">
        <svg width="10" height="10" viewBox="0 0 10 10"><line x1="0" y1="0" x2="10" y2="10" stroke="currentColor" strokeWidth="1.2" /><line x1="10" y1="0" x2="0" y2="10" stroke="currentColor" strokeWidth="1.2" /></svg>
      </button>
    </div>
  );
}

export function App() {
  const { currentPage, setPage, isRecording, error, setError } = useAppStore();
  const { isConnected } = useBackend();

  return (
    <div className="app-layout">
      {/* Custom title bar — draggable, spans full width */}
      <div className="custom-titlebar">
        <span className="custom-titlebar__label">VoiceScribe</span>
        <WindowControls />
      </div>

      {/* Body below title bar */}
      <div className="app-body">
        {/* Sidebar */}
        <aside className="sidebar">
          {/* Navigation */}
          <nav className="sidebar__nav">
            {NAV_ITEMS.map(({ page, icon, label }) => (
              <button
                key={page}
                className={`sidebar__item${currentPage === page ? ' sidebar__item--active' : ''}`}
                onClick={() => setPage(page)}
              >
                <span className="sidebar__icon">{icon}</span>
                <span>{label}</span>
                {page === 'recording' && isRecording && (
                  <span
                    className="badge badge--danger"
                    style={{ marginLeft: 'auto', fontSize: 10 }}
                  >
                    REC
                  </span>
                )}
              </button>
            ))}
          </nav>

          {/* Status footer */}
          <div className="sidebar__footer">
            <div className="sidebar__status">
              <span
                className={`sidebar__status-dot ${
                  isConnected
                    ? 'sidebar__status-dot--connected'
                    : 'sidebar__status-dot--disconnected'
                }`}
              />
              <span>{isConnected ? 'Backend connected' : 'Backend disconnected'}</span>
            </div>
          </div>
        </aside>

        {/* Main content */}
        <main className="main-content">
          {error && (
            <div className="error-banner">
              <span>&#9888;</span>
              <span style={{ flex: 1 }}>{error}</span>
              <button
                className="btn btn--ghost btn--sm"
                onClick={() => setError(null)}
                style={{ padding: '2px 8px', fontSize: 11 }}
              >
                Dismiss
              </button>
            </div>
          )}
          <div className="page" style={{ display: 'flex', flexDirection: 'column' }}>
            <PageContent />
          </div>
        </main>
      </div>
    </div>
  );
}
