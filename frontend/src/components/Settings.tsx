import { useEffect, useState } from 'react';
import { useAppStore } from '@/stores/appStore';
import { useBackend } from '@/hooks/useBackend';
import type { AppSettings, AudioDevice } from '@/types';

const defaultSettings: AppSettings = {
  whisperModel: 'small',
  language: 'auto',
  inputDevice: 'default',
  outputDevice: 'default',
  speakerThreshold: 0.7,
  dataPath: '',
};

export function Settings() {
  const { settings, setSettings, setError } = useAppStore();
  const { sendCommand } = useBackend();

  const [local, setLocal] = useState<AppSettings>(settings || defaultSettings);
  const [devices, setDevices] = useState<AudioDevice[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    loadAll();
  }, []);

  async function loadAll() {
    setLoading(true);
    try {
      const [settingsRes, devicesRes] = await Promise.all([
        sendCommand('get_settings'),
        sendCommand('get_devices'),
      ]);
      if (settingsRes && typeof settingsRes === 'object') {
        const mapped: AppSettings = {
          whisperModel: settingsRes.whisper_model || 'small',
          language: settingsRes.language || 'auto',
          inputDevice: settingsRes.input_device || 'default',
          outputDevice: settingsRes.output_device || 'default',
          speakerThreshold: settingsRes.speaker_threshold ?? 0.7,
          dataPath: settingsRes.db_path || settingsRes.audio_save_path || '',
        };
        setLocal(mapped);
        setSettings(mapped);
      }
      if (Array.isArray(devicesRes)) {
        setDevices(devicesRes.map((d: any) => ({
          id: String(d.index ?? d.id ?? ''),
          name: d.name || `Device ${d.index}`,
          isDefault: !!d.isDefault || !!d.is_default,
        })));
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to load settings');
    } finally {
      setLoading(false);
    }
  }

  function update(key: keyof AppSettings, value: any) {
    setLocal((prev) => ({ ...prev, [key]: value }));
    setSaved(false);
  }

  async function handleSave() {
    setSaving(true);
    try {
      // Backend expects {key, value} per setting — send each changed key
      const keyMap: Record<string, string> = {
        whisperModel: 'whisper_model',
        language: 'language',
        inputDevice: 'input_device',
        outputDevice: 'output_device',
        speakerThreshold: 'speaker_threshold',
        dataPath: 'data_path',
      };
      const prev = settings || defaultSettings;
      for (const [frontKey, backKey] of Object.entries(keyMap)) {
        const val = (local as any)[frontKey];
        if (val !== (prev as any)[frontKey]) {
          await sendCommand('update_settings', { key: backKey, value: val });
        }
      }
      setSettings(local);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err: any) {
      setError(err?.message || 'Failed to save settings');
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="page page-enter">
        <div className="loading-center">
          <div className="spinner" />
          Loading settings...
        </div>
      </div>
    );
  }

  return (
    <div className="page page-enter">
      <div className="page-header">
        <h1 className="page-title">Settings</h1>
        <div className="flex gap-8 items-center">
          {saved && (
            <span style={{ fontSize: 13, color: 'var(--success)', fontWeight: 500 }}>
              Saved
            </span>
          )}
          <button className="btn btn--primary btn--sm" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving...' : 'Save Settings'}
          </button>
        </div>
      </div>

      <div className="card">
        <div className="settings-grid">
          {/* Whisper Model */}
          <div className="form-group">
            <label className="form-label">Whisper Model</label>
            <select
              className="form-select"
              value={local.whisperModel}
              onChange={(e) => update('whisperModel', e.target.value)}
            >
              <option value="tiny">Tiny (fastest, least accurate)</option>
              <option value="small">Small (balanced)</option>
              <option value="medium">Medium (more accurate)</option>
              <option value="large">Large (most accurate, slowest)</option>
            </select>
          </div>

          {/* Language */}
          <div className="form-group">
            <label className="form-label">Language</label>
            <select
              className="form-select"
              value={local.language}
              onChange={(e) => update('language', e.target.value)}
            >
              <option value="auto">Auto-detect</option>
              <option value="en">English</option>
              <option value="ru">Русский</option>
              <option value="uk">Українська</option>
              <option value="es">Español</option>
            </select>
          </div>

          {/* Input device */}
          <div className="form-group">
            <label className="form-label">Input Device (Microphone)</label>
            <select
              className="form-select"
              value={local.inputDevice}
              onChange={(e) => update('inputDevice', e.target.value)}
            >
              {devices.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}{d.isDefault ? ' (Default)' : ''}
                </option>
              ))}
            </select>
          </div>

          {/* Output device */}
          <div className="form-group">
            <label className="form-label">Output Device (Speaker)</label>
            <select
              className="form-select"
              value={local.outputDevice}
              onChange={(e) => update('outputDevice', e.target.value)}
            >
              {devices.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}{d.isDefault ? ' (Default)' : ''}
                </option>
              ))}
            </select>
          </div>

          {/* Speaker threshold */}
          <div className="form-group form-group--full">
            <label className="form-label">
              Speaker Recognition Threshold: {local.speakerThreshold.toFixed(2)}
            </label>
            <input
              type="range"
              className="form-range"
              min="0.3"
              max="0.95"
              step="0.05"
              value={local.speakerThreshold}
              onChange={(e) => update('speakerThreshold', parseFloat(e.target.value))}
            />
            <div className="flex justify-between" style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
              <span>More flexible</span>
              <span>More strict</span>
            </div>
          </div>

          {/* Data path */}
          <div className="form-group form-group--full">
            <label className="form-label">Data Storage Path</label>
            <input
              className="form-input"
              value={local.dataPath}
              readOnly
              style={{ opacity: 0.7, cursor: 'default' }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
