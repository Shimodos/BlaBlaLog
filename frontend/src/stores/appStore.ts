import { create } from 'zustand';
import type { Meeting, Speaker, TranscriptSegment, PageName, AppSettings } from '@/types';

interface ProcessingState {
  isProcessing: boolean;
  stage: string;       // 'transcription' | 'diarization' | 'identification' | 'complete' | 'error'
  progress: number;    // 0-100
  message: string;
}

interface AppState {
  // Navigation
  currentPage: PageName;
  setPage: (page: PageName) => void;

  // Recording state
  isRecording: boolean;
  recordingDuration: number;
  currentMeetingId: string | null;
  liveSegments: TranscriptSegment[];

  // Audio levels (VU meter)
  audioLevels: { mic: number; loopback: number };
  setAudioLevels: (levels: { mic?: number; loopback?: number }) => void;

  // Processing state (after recording stops)
  processing: ProcessingState;
  setProcessing: (p: Partial<ProcessingState>) => void;

  // Data
  meetings: Meeting[];
  speakers: Speaker[];
  selectedMeetingId: string | null;
  settings: AppSettings | null;

  // Logs
  logs: string[];
  addLog: (line: string) => void;
  clearLogs: () => void;

  // Loading / error
  isLoading: boolean;
  error: string | null;

  // Actions — recording
  setRecording: (recording: boolean) => void;
  setRecordingDuration: (duration: number) => void;
  setCurrentMeetingId: (id: string | null) => void;
  addLiveSegment: (segment: TranscriptSegment) => void;
  updateLiveSegment: (segment: TranscriptSegment) => void;
  upsertLiveSegment: (segment: TranscriptSegment) => void;
  clearLiveSegments: () => void;

  // Actions — data
  setMeetings: (meetings: Meeting[]) => void;
  setSpeakers: (speakers: Speaker[]) => void;
  setSelectedMeetingId: (id: string | null) => void;
  setSettings: (settings: AppSettings) => void;

  // Actions — UI
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
}

export const useAppStore = create<AppState>((set) => ({
  // Navigation
  currentPage: 'recording',
  setPage: (page) => set({ currentPage: page, error: null }),

  // Recording
  isRecording: false,
  recordingDuration: 0,
  currentMeetingId: null,
  liveSegments: [],

  // Audio levels
  audioLevels: { mic: 0, loopback: 0 },
  setAudioLevels: (levels) =>
    set((state) => ({
      audioLevels: { ...state.audioLevels, ...levels },
    })),

  // Processing
  processing: { isProcessing: false, stage: '', progress: 0, message: '' },
  setProcessing: (p) =>
    set((state) => ({
      processing: { ...state.processing, ...p },
    })),

  setRecording: (isRecording) => set({ isRecording }),
  setRecordingDuration: (recordingDuration) => set({ recordingDuration }),
  setCurrentMeetingId: (currentMeetingId) => set({ currentMeetingId }),
  addLiveSegment: (segment) =>
    set((state) => ({ liveSegments: [...state.liveSegments, segment] })),
  updateLiveSegment: (segment) =>
    set((state) => ({
      liveSegments: state.liveSegments.map((s) =>
        s.id === segment.id ? segment : s,
      ),
    })),
  upsertLiveSegment: (segment) =>
    set((state) => ({
      liveSegments: state.liveSegments.some((s) => s.id === segment.id)
        ? state.liveSegments.map((s) => s.id === segment.id ? segment : s)
        : [...state.liveSegments, segment],
    })),
  clearLiveSegments: () => set({ liveSegments: [] }),

  // Data
  meetings: [],
  speakers: [],
  selectedMeetingId: null,
  settings: null,

  setMeetings: (meetings) => set({ meetings }),
  setSpeakers: (speakers) => set({ speakers }),
  setSelectedMeetingId: (id) => set({ selectedMeetingId: id }),
  setSettings: (settings) => set({ settings }),

  // Logs
  logs: [],
  addLog: (line) =>
    set((state) => ({
      logs: [...state.logs.slice(-499), line],  // keep last 500 lines
    })),
  clearLogs: () => set({ logs: [] }),

  // UI
  isLoading: false,
  error: null,
  setLoading: (isLoading) => set({ isLoading }),
  setError: (error) => set({ error }),
}));
