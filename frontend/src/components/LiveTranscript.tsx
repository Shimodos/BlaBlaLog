import { useEffect, useRef, useState, useCallback } from 'react';
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

function CopyButton({ text, title, size = 'small' }: { text: string; title?: string; size?: 'small' | 'normal' }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* ignore */ }
  }, [text]);

  return (
    <button
      className={`copy-btn${size === 'normal' ? ' copy-btn--normal' : ''}`}
      onClick={handleCopy}
      title={title || 'Copy'}
    >
      {copied ? (
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <path d="M3 7.5L5.5 10L11 4" stroke="var(--success)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      ) : (
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <rect x="4.5" y="4.5" width="7" height="7" rx="1" stroke="currentColor" strokeWidth="1.2" />
          <path d="M9.5 4.5V3C9.5 2.44772 9.05228 2 8.5 2H3C2.44772 2 2 2.44772 2 3V8.5C2 9.05228 2.44772 9.5 3 9.5H4.5" stroke="currentColor" strokeWidth="1.2" />
        </svg>
      )}
      {size === 'normal' && <span>{copied ? 'Copied!' : 'Copy All'}</span>}
    </button>
  );
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

  // Build full transcript text for "Copy All"
  const fullText = segments
    .map((seg) => `[${formatTimestamp(seg.start_time)}] ${seg.speaker_label}: ${seg.text}`)
    .join('\n');

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
    <div className="transcript-container">
      <div className="transcript-toolbar">
        <CopyButton text={fullText} title="Copy entire transcript" size="normal" />
      </div>
      <div
        ref={scrollRef}
        className="transcript"
        style={{ overflowY: 'auto', flex: 1, padding: '8px 0' }}
      >
        {segments.map((seg) => {
          const isPartial = seg.id === partialSegmentId;
          const color = getSpeakerColor(seg.speaker_label);
          const segText = `${seg.speaker_label}: ${seg.text}`;

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
              <CopyButton text={segText} title="Copy this segment" />
            </div>
          );
        })}
      </div>
    </div>
  );
}
