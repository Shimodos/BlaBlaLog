import { useEffect, useState } from 'react';
import { useBackend } from '@/hooks/useBackend';

const STAGE_LABELS: Record<string, string> = {
  starting: 'Starting backend...',
  loading: 'Loading Python environment...',
  models: 'Loading ML models...',
  ready: 'Almost ready...',
};

export function BackendInitModal() {
  const { isConnected } = useBackend();
  const [stage, setStage] = useState('starting');
  const [message, setMessage] = useState('Initializing backend...');
  const [dots, setDots] = useState('');
  const [dismissed, setDismissed] = useState(false);

  // Listen for init-status events from Electron
  useEffect(() => {
    if (!window.electronAPI?.onBackendInitStatus) return;
    window.electronAPI.onBackendInitStatus((status) => {
      if (status.stage) setStage(status.stage);
      if (status.message) setMessage(status.message);
    });
  }, []);

  // Animate dots
  useEffect(() => {
    if (isConnected) return;
    const id = setInterval(() => {
      setDots((d) => (d.length >= 3 ? '' : d + '.'));
    }, 500);
    return () => clearInterval(id);
  }, [isConnected]);

  // Auto-dismiss when connected
  useEffect(() => {
    if (isConnected) {
      const timer = setTimeout(() => setDismissed(true), 600);
      return () => clearTimeout(timer);
    }
    setDismissed(false);
  }, [isConnected]);

  if (dismissed) return null;

  const stageLabel = STAGE_LABELS[stage] || 'Starting backend...';

  return (
    <div className={`init-overlay${isConnected ? ' init-overlay--fade-out' : ''}`}>
      <div className="init-modal">
        <div className="init-modal__icon">
          <div className="init-modal__spinner" />
        </div>
        <h2 className="init-modal__title">
          {isConnected ? 'Backend connected!' : stageLabel}
        </h2>
        <p className="init-modal__message">
          {isConnected
            ? 'Ready to use'
            : message + dots
          }
        </p>
        {!isConnected && (
          <div className="init-modal__progress">
            <div className="init-modal__progress-bar" />
          </div>
        )}
      </div>
    </div>
  );
}
