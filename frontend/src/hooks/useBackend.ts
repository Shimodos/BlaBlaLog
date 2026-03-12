import { useEffect, useRef, useState, useCallback } from 'react';
import { useAppStore } from '@/stores/appStore';

// Mock data for browser development
const mockMeetings = [
  {
    id: 'mock-1',
    title: 'Team Standup',
    started_at: '2026-03-12T09:00:00Z',
    ended_at: '2026-03-12T09:15:00Z',
    duration_seconds: 900,
    language: 'en',
  },
  {
    id: 'mock-2',
    title: 'Project Review',
    started_at: '2026-03-11T14:00:00Z',
    ended_at: '2026-03-11T15:30:00Z',
    duration_seconds: 5400,
    language: 'en',
  },
];

const mockSpeakers = [
  { id: 'sp-1', name: 'Alice Johnson', created_at: '2026-03-01T10:00:00Z' },
  { id: 'sp-2', name: 'Bob Smith', created_at: '2026-03-05T14:00:00Z' },
];

const mockDevices = [
  { id: 'default', name: 'Default Microphone', isDefault: true },
  { id: 'usb-mic', name: 'USB Condenser Mic', isDefault: false },
];

const mockSettings = {
  whisperModel: 'small',
  language: 'auto',
  inputDevice: 'default',
  outputDevice: 'default',
  speakerThreshold: 0.7,
  dataPath: 'C:\\VoiceScribe\\data',
};

const mockSegments = [
  {
    id: 1,
    meeting_id: 'mock-1',
    speaker_id: 'sp-1',
    speaker_label: 'Alice Johnson',
    start_time: 0,
    end_time: 5.2,
    text: 'Good morning everyone. Let\'s start with the standup.',
    confidence: 0.95,
  },
  {
    id: 2,
    meeting_id: 'mock-1',
    speaker_id: 'sp-2',
    speaker_label: 'Bob Smith',
    start_time: 5.5,
    end_time: 12.1,
    text: 'Yesterday I finished the API integration. Today I\'ll work on the frontend components.',
    confidence: 0.91,
  },
];

function getMockResponse(method: string, params?: any): any {
  switch (method) {
    case 'list_meetings':
      return mockMeetings;
    case 'get_meeting':
      return {
        meeting: mockMeetings.find((m) => m.id === params?.meeting_id) || mockMeetings[0],
        segments: mockSegments,
      };
    case 'list_speakers':
      return mockSpeakers;
    case 'get_input_devices':
    case 'get_devices':
      return mockDevices;
    case 'get_loopback_devices':
      return [
        { index: 0, name: 'Speakers (Loopback)', is_loopback: true },
        { index: 1, name: 'Headphones (Loopback)', is_loopback: true },
      ];
    case 'get_settings':
      return {
        whisper_model: mockSettings.whisperModel,
        language: mockSettings.language,
        speaker_threshold: mockSettings.speakerThreshold,
        db_path: mockSettings.dataPath,
      };
    case 'start_recording':
      return { meeting_id: 'mock-live-' + Date.now(), status: 'recording' };
    case 'stop_recording':
      return { status: 'stopped' };
    case 'delete_meeting':
      return { success: true };
    case 'delete_speaker':
      return { success: true };
    case 'update_meeting':
      return { success: true };
    case 'update_settings':
      return { success: true };
    case 'export':
      return { content: '# Meeting Transcript\n\nExported content here...', filename: 'export.md' };
    case 'create_speaker_profile':
      return { id: 'sp-new', name: params?.name || 'New Speaker', created_at: new Date().toISOString() };
    default:
      return { ok: true };
  }
}

export function useBackend() {
  const [isConnected, setIsConnected] = useState(false);
  const listenersRef = useRef<Set<(data: any) => void>>(new Set());
  const hasElectron = typeof window !== 'undefined' && !!window.electronAPI;

  useEffect(() => {
    let cancelled = false;

    async function checkConnection() {
      if (hasElectron) {
        try {
          const status: any = await window.electronAPI!.getBackendStatus();
          if (!cancelled) setIsConnected(status?.running ?? false);
        } catch {
          if (!cancelled) setIsConnected(false);
        }
      } else {
        // Mock mode — always connected
        if (!cancelled) setIsConnected(true);
      }
    }

    checkConnection();
    const interval = setInterval(checkConnection, 5000);

    if (hasElectron) {
      window.electronAPI!.onBackendEvent((data: any) => {
        listenersRef.current.forEach((cb) => cb(data));
      });
      // Forward backend stderr to log store
      window.electronAPI!.onBackendLog((line: string) => {
        useAppStore.getState().addLog(line);
      });
    }

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [hasElectron]);

  const sendCommand = useCallback(
    async (method: string, params?: any): Promise<any> => {
      if (hasElectron) {
        const response: any = await window.electronAPI!.sendToBackend(method, params);
        // JSON-RPC response: {jsonrpc, result, id} or {jsonrpc, error, id}
        if (response?.error) {
          throw new Error(response.error.message || 'Backend error');
        }
        return response?.result !== undefined ? response.result : response;
      }
      // Mock: simulate network delay
      await new Promise((r) => setTimeout(r, 200 + Math.random() * 300));
      return getMockResponse(method, params);
    },
    [hasElectron],
  );

  const subscribe = useCallback((callback: (data: any) => void) => {
    listenersRef.current.add(callback);
    return () => {
      listenersRef.current.delete(callback);
    };
  }, []);

  return { sendCommand, isConnected, subscribe };
}
