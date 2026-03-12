import { useEffect, useRef } from 'react';
import type { TranscriptSegment } from '@/types';

const SPEAKER_COLORS = [
  'var(--speaker-1)',
  'var(--speaker-2)',
  'var(--speaker-3)',
  'var(--speaker-4)',
  'var(--speaker-5)',
  'var(--speaker-6)',
  'var(--speaker-7)',
  'var(--speaker-8)',
];

function getSpeakerColor(label: string): string {
  let hash = 0;
  for (let i = 0; i < label.length; i++) {
    hash = label.charCodeAt(i) + ((hash << 5) - hash);
  }
  return SPEAKER_COLORS[Math.abs(hash) % SPEAKER_COLORS.length];
}

function formatTimestamp(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

interface LiveTranscriptProps {
  segments: TranscriptSegment[];
  partialSegmentId?: number | null;
}

export function LiveTranscript({ segments, partialSegmentId }: LiveTranscriptProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const userScrolledUp = useRef(false);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const handleScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = el;
      userScrolledUp.current = scrollHeight - scrollTop - clientHeight > 60;
    };

    el.addEventListener('scroll', handleScroll);
    return () => el.removeEventListener('scroll', handleScroll);
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && !userScrolledUp.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [segments]);

  if (segments.length === 0) {
    return (
      <div className="empty-state" style={{ padding: '40px 20px' }}>
        <div className="empty-state__icon">&#127908;</div>
        <div className="empty-state__text">
          Transcript will appear here once recording starts...
        </div>
      </div>
    );
  }

  return (
    <div
      ref={scrollRef}
      className="transcript"
      style={{ overflowY: 'auto', flex: 1, padding: '8px 0' }}
    >
      {segments.map((seg) => {
        const isPartial = seg.id === partialSegmentId;
        const color = getSpeakerColor(seg.speaker_label);

        return (
          <div key={seg.id} className="transcript-line">
            <span className="transcript-line__time">
              {formatTimestamp(seg.start_time)}
            </span>
            <span
              className="transcript-line__speaker"
              style={{ color }}
            >
              {seg.speaker_label}
            </span>
            <span
              className={`transcript-line__text${isPartial ? ' transcript-line__text--partial' : ''}`}
            >
              {seg.text}
            </span>
          </div>
        );
      })}
    </div>
  );
}
