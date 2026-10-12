import React from 'react';
import { X, ExternalLink, Bookmark, Clock, User, Mic } from 'lucide-react';
import type { SourceMetadata } from '../api/types';

interface SourcesDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  sources: SourceMetadata[];
  versionNumber: number;
}

export const SourcesDrawer: React.FC<SourcesDrawerProps> = ({
  isOpen,
  onClose,
  sources,
  versionNumber,
}) => {
  if (!isOpen) return null;

  return (
    <div className="drawer-backdrop" onClick={onClose} role="dialog" aria-modal="true">
      <div className="drawer-panel" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Bookmark size={18} style={{ color: 'var(--primary)' }} />
            <h2 className="drawer-title">Grounded Evidence (v{versionNumber})</h2>
          </div>
          <button
            type="button"
            className="btn-secondary"
            style={{ padding: '0.35rem 0.5rem', borderRadius: '50%' }}
            onClick={onClose}
            aria-label="Close sources drawer"
          >
            <X size={16} />
          </button>
        </div>

        <div className="drawer-content">
          <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            {sources.length > 0
              ? `${sources.length} verified transcript excerpts retrieved from Lenny’s Podcast corpus and grounded in this essay version.`
              : 'No podcast sources recorded for this version.'}
          </p>

          {sources.map((source, index) => {
            const guestName = source.guest || source.speaker || 'Unknown Guest';
            const episodeTitle = source.title || 'Untitled Episode';
            const chunkId = source.chunk_id;
            const sourceUrl = source.source_url;
            const excerpt = source.chunk_text;
            const timestamp = source.timestamp || (source.start_time_seconds ? `${Math.floor(source.start_time_seconds / 60)}m` : null);

            return (
              <div key={chunkId || index} className="source-card">
                <div className="source-header">
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', marginBottom: '0.2rem' }}>
                      <User size={13} style={{ color: 'var(--primary)' }} />
                      <span className="source-guest">{guestName}</span>
                      <span className="version-chip" style={{ fontSize: '0.7rem' }}>
                        Source {index + 1}
                      </span>
                    </div>
                    <div className="source-episode">{episodeTitle}</div>
                  </div>

                  {chunkId && (
                    <span className="version-chip" style={{ fontSize: '0.7rem' }}>
                      #{chunkId}
                    </span>
                  )}
                </div>

                {excerpt && (
                  <div className="source-excerpt">
                    "{excerpt}"
                  </div>
                )}

                <div className="source-footer">
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                    {timestamp && (
                      <>
                        <Clock size={12} />
                        <span>{timestamp}</span>
                      </>
                    )}
                    {source.speaker && source.speaker !== source.guest && (
                      <>
                        <Mic size={12} style={{ marginLeft: '0.4rem' }} />
                        <span>Speaker: {source.speaker}</span>
                      </>
                    )}
                  </div>

                  {sourceUrl ? (
                    <a
                      href={sourceUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ display: 'inline-flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.75rem' }}
                    >
                      <span>Listen / View</span>
                      <ExternalLink size={12} />
                    </a>
                  ) : (
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-faint)' }}>Verified In Corpus</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
