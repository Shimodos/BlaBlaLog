import { useEffect, useRef } from 'react';
import { useAppStore } from '@/stores/appStore';

export function LogViewer() {
  const logs = useAppStore((s) => s.logs);
  const clearLogs = useAppStore((s) => s.clearLogs);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs.length]);

  return (
    <div className="log-viewer page-enter" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>Backend Logs</h2>
        <div style={{ display: 'flex', gap: 8 }}>
          <span style={{ fontSize: 12, color: 'var(--text-muted)', alignSelf: 'center' }}>
            {logs.length} lines
          </span>
          <button className="btn btn--ghost btn--sm" onClick={clearLogs}>
            Clear
          </button>
        </div>
      </div>

      <div
        className="card"
        style={{
          flex: 1,
          minHeight: 0,
          overflow: 'auto',
          fontFamily: 'Consolas, "Courier New", monospace',
          fontSize: 12,
          lineHeight: 1.6,
          padding: 12,
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-all',
        }}
      >
        {logs.length === 0 ? (
          <div style={{ color: 'var(--text-muted)', textAlign: 'center', padding: 40 }}>
            No logs yet. Start a recording to see backend activity.
          </div>
        ) : (
          logs.map((line, i) => (
            <div
              key={i}
              style={{
                color: line.includes('ERROR') || line.includes('CRITICAL')
                  ? 'var(--danger)'
                  : line.includes('WARNING')
                  ? '#f0a030'
                  : line.includes('INFO')
                  ? 'var(--text-secondary)'
                  : 'var(--text-muted)',
              }}
            >
              {line}
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
