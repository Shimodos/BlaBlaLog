export interface Meeting {
  id: string;
  title: string;
  started_at: string;
  ended_at: string;
  duration_seconds: number;
  language: string;
}

export interface Speaker {
  id: string;
  name: string;
  created_at: string;
}

export interface TranscriptSegment {
  id: number;
  meeting_id: string;
  speaker_id: string | null;
  speaker_label: string;
  start_time: number;
  end_time: number;
  text: string;
  confidence: number;
}

export interface AudioDevice {
  id: string;
  name: string;
  isDefault: boolean;
}

export interface AppSettings {
  whisperModel: 'tiny' | 'small' | 'medium' | 'large';
  language: 'ru' | 'en' | 'auto';
  inputDevice: string;
  outputDevice: string;
  speakerThreshold: number;
  dataPath: string;
}

export interface ExportOptions {
  format: 'md' | 'txt' | 'srt' | 'json';
  includeTimestamps: boolean;
  includeSpeakers: boolean;
}

export type PageName = 'recording' | 'history' | 'meeting-detail' | 'speakers' | 'settings' | 'logs';

export interface ElectronAPI {
  sendToBackend(method: string, params?: any): Promise<any>;
  getBackendStatus(): Promise<boolean>;
  onBackendEvent(callback: (data: any) => void): void;
  onBackendLog(callback: (line: string) => void): void;
  onBackendInitStatus(callback: (status: { stage: string; message: string }) => void): void;
  minimize(): void;
  maximize(): void;
  close(): void;
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI;
  }
}
