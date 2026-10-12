import React, { useState, useEffect } from 'react';
import { BookOpen, Calendar, FileText, Loader2, AlertCircle, RefreshCw, PlusCircle } from 'lucide-react';
import { apiClient } from '../api/client';
import type { WritingArtifactListItem, WritingArtifactResponse } from '../api/types';

interface EssayLibraryProps {
  onOpenArtifact: (artifact: WritingArtifactResponse) => void;
  onNewEssay?: () => void;
  onBackToChat?: () => void;
}

export const EssayLibrary: React.FC<EssayLibraryProps> = ({ onOpenArtifact, onNewEssay, onBackToChat }) => {
  const [artifacts, setArtifacts] = useState<WritingArtifactListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadArtifacts = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await apiClient.listArtifacts(50, 0);
      setArtifacts(response.artifacts);
      setTotal(response.total);
    } catch (err: any) {
      setError(err.message || 'Failed to load artifacts.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadArtifacts();
  }, []);

  const handleSelectArtifact = async (artifactId: string) => {
    try {
      const artifact = await apiClient.getArtifact(artifactId);
      onOpenArtifact(artifact);
    } catch (err: any) {
      setError(`Cannot load artifact: ${err.message}`);
    }
  };

  return (
    <div className="library-container">
      <div className="library-header">
        <div>
          <h1 className="library-title">Artifacts & Library</h1>
          <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>
            {total} grounded essay and document artifact{total === 1 ? '' : 's'} saved in PostgreSQL.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '0.5rem' }}>
          {onBackToChat && (
            <button
              type="button"
              className="btn-secondary"
              onClick={onBackToChat}
              style={{ fontSize: '0.85rem' }}
            >
              Back to Chat
            </button>
          )}
          <button
            type="button"
            className="btn-secondary"
            onClick={loadArtifacts}
            disabled={isLoading}
            aria-label="Refresh artifacts list"
          >
            <RefreshCw size={14} className={isLoading ? 'animate-spin' : ''} />
            <span>Refresh</span>
          </button>
          <button type="button" className="btn-primary" onClick={onNewEssay}>
            <PlusCircle size={15} />
            <span>New Essay</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="error-banner" role="alert">
          <AlertCircle size={18} />
          <div style={{ flex: 1 }}>{error}</div>
          <button type="button" className="btn-secondary" onClick={loadArtifacts}>
            Retry
          </button>
        </div>
      )}

      {isLoading ? (
        <div style={{ display: 'flex', justifyContent: 'center', padding: '4rem 0' }}>
          <Loader2 size={32} className="animate-spin" style={{ color: 'var(--primary)' }} />
        </div>
      ) : artifacts.length === 0 ? (
        <div
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--border-light)',
            borderRadius: 'var(--radius-lg)',
            padding: '3.5rem 2rem',
            textAlign: 'center',
          }}
        >
          <BookOpen size={42} style={{ color: 'var(--text-muted)', margin: '0 auto 1rem' }} />
          <h2 style={{ fontSize: '1.2rem', fontWeight: 700, color: 'var(--text-main)' }}>No Essays Saved Yet</h2>
          <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', maxWidth: '420px', margin: '0.5rem auto 1.5rem' }}>
            Research and draft your first Ship 30 for 30 essay grounded in Lenny’s Podcast transcripts.
          </p>
          <button type="button" className="btn-primary" onClick={onNewEssay}>
            <PlusCircle size={16} />
            <span>Compose Your First Essay</span>
          </button>
        </div>
      ) : (
        <div className="essays-grid">
          {artifacts.map((art) => {
            const formattedDate = new Date(art.updated_at).toLocaleDateString(undefined, {
              year: 'numeric',
              month: 'short',
              day: 'numeric',
            });

            return (
              <div
                key={art.id}
                className="essay-card"
                onClick={() => handleSelectArtifact(art.id)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    handleSelectArtifact(art.id);
                  }
                }}
              >
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                    <span className="version-chip">v{art.latest_version_number}</span>
                    <span className={`job-status-pill ${art.status === 'completed' ? 'status-completed' : 'status-failed'}`}>
                      {art.status === 'completed' ? 'Accepted' : 'Needs Revision'}
                    </span>
                  </div>
                  <h3 className="card-title">{art.title}</h3>
                </div>

                <div className="card-meta">
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                    <FileText size={13} />
                    <span>{art.latest_word_count} words</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', marginLeft: 'auto' }}>
                    <Calendar size={13} />
                    <span>{formattedDate}</span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
