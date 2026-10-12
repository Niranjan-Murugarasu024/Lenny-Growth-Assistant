import React, { useState } from 'react';
import { BookOpen, ExternalLink, ChevronDown, ChevronUp, Clock, Play } from 'lucide-react';
import type { SourceReference } from '../api/types';

interface SourcesSectionProps {
  sources: SourceReference[];
}

export const SourcesSection: React.FC<SourcesSectionProps> = ({ sources }) => {
  const [isExpanded, setIsExpanded] = useState<boolean>(true);

  if (!sources || sources.length === 0) {
    return null;
  }

  return (
    <div className="sources-section" style={{ marginTop: '1.25rem', borderTop: '1px solid var(--border-light)', paddingTop: '0.85rem' }}>
      <button
        type="button"
        onClick={() => setIsExpanded(!isExpanded)}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          width: '100%',
          background: 'transparent',
          border: 'none',
          padding: '0.35rem 0',
          cursor: 'pointer',
          color: 'var(--text-secondary)',
          fontSize: '0.85rem',
          fontWeight: 600,
        }}
      >
        <span style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
          <BookOpen size={15} style={{ color: 'var(--primary)' }} />
          <span>Verified Sources from Lenny's Podcast ({sources.length})</span>
        </span>
        {isExpanded ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
      </button>

      {isExpanded && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem', marginTop: '0.65rem' }}>
          {sources.map((src, idx) => {
            const hasYoutube = Boolean(src.youtube_url || src.youtube_video_id);
            const youtubeHref =
              src.youtube_url ||
              (src.youtube_video_id
                ? `https://www.youtube.com/watch?v=${src.youtube_video_id}${src.start_time_seconds ? `&t=${Math.floor(src.start_time_seconds)}s` : ''}`
                : undefined);

            const externalUrl = youtubeHref || src.source_url;

            return (
              <div
                key={src.chunk_id || idx}
                style={{
                  backgroundColor: 'var(--bg-surface)',
                  border: '1px solid var(--border-light)',
                  borderRadius: 'var(--radius-md)',
                  padding: '0.75rem 0.95rem',
                  fontSize: '0.825rem',
                  boxShadow: 'var(--shadow-sm)',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '0.75rem', marginBottom: '0.35rem' }}>
                  <div>
                    <span style={{ fontWeight: 700, color: 'var(--text-main)', fontSize: '0.875rem' }}>
                      {src.guest}
                    </span>
                    <span style={{ color: 'var(--text-muted)', margin: '0 0.35rem' }}>·</span>
                    <span style={{ color: 'var(--text-secondary)', fontStyle: 'italic' }}>
                      "{src.title}"
                    </span>
                  </div>

                  {src.timestamp && (
                    <span
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '0.25rem',
                        fontSize: '0.75rem',
                        padding: '0.15rem 0.45rem',
                        borderRadius: 'var(--radius-sm)',
                        backgroundColor: 'var(--bg-subtle)',
                        color: 'var(--text-muted)',
                        fontFamily: 'var(--font-mono)',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      <Clock size={11} />
                      {src.timestamp}
                    </span>
                  )}
                </div>

                <blockquote
                  style={{
                    margin: '0.45rem 0 0.55rem',
                    padding: '0.5rem 0.75rem',
                    border: '1px solid var(--border-light)',
                    backgroundColor: 'var(--bg-subtle)',
                    borderRadius: 'var(--radius-sm)',
                    color: 'var(--text-secondary)',
                    lineHeight: 1.55,
                    fontStyle: 'normal',
                  }}
                >
                  "{src.excerpt || (src as any).chunk_text}"
                </blockquote>

                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem', marginTop: '0.4rem', fontSize: '0.75rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                    {hasYoutube && youtubeHref ? (
                      <a
                        href={youtubeHref}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '0.3rem',
                          color: '#dc2626',
                          fontWeight: 600,
                          textDecoration: 'none',
                          padding: '0.2rem 0.45rem',
                          borderRadius: 'var(--radius-sm)',
                          backgroundColor: '#fef2f2',
                          border: '1px solid #fee2e2',
                        }}
                      >
                        <Play size={12} fill="#dc2626" />
                        <span>Watch Episode {src.timestamp ? `(${src.timestamp})` : ''}</span>
                        <ExternalLink size={11} />
                      </a>
                    ) : externalUrl ? (
                      <a
                        href={externalUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '0.3rem',
                          color: 'var(--primary)',
                          fontWeight: 600,
                          textDecoration: 'none',
                        }}
                      >
                        <span>Canonical Source</span>
                        <ExternalLink size={11} />
                      </a>
                    ) : (
                      <span style={{ color: 'var(--text-muted)' }}>Podcast Archive Transcript</span>
                    )}
                  </div>

                  <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '0.72rem' }}>
                    Chunk #{src.chunk_id || (src as any).id}
                    {src.cosine_distance !== undefined && ` · dist: ${src.cosine_distance.toFixed(3)}`}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
