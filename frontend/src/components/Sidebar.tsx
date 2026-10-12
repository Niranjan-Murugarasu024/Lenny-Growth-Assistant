import React from 'react';
import { Plus, MessageSquare, Library, ChevronLeft, ChevronRight, Cpu } from 'lucide-react';
import type { ChatSession } from '../api/types';

interface SidebarProps {
  sessions: ChatSession[];
  activeSessionId: string | null;
  isOpen: boolean;
  onToggleOpen: () => void;
  onSelectSession: (sessionId: string) => void;
  onNewChat: () => void;
  onOpenLibrary: () => void;
  isLibraryActive: boolean;
  providerInfo?: { provider: string; model: string } | null;
}

export const Sidebar: React.FC<SidebarProps> = ({
  sessions,
  activeSessionId,
  isOpen,
  onToggleOpen,
  onSelectSession,
  onNewChat,
  onOpenLibrary,
  isLibraryActive,
  providerInfo,
}) => {
  const formatSessionTime = (isoString: string): string => {
    try {
      const date = new Date(isoString);
      const now = new Date();
      const diffMs = now.getTime() - date.getTime();
      const diffMins = Math.floor(diffMs / (1000 * 60));
      const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
      const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

      if (diffMins < 5) return 'Just now';
      if (diffMins < 60) return `${diffMins}m ago`;
      if (diffHours < 24) return `${diffHours}h ago`;
      if (diffDays < 7) return `${diffDays}d ago`;
      return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    } catch {
      return '';
    }
  };

  return (
    <aside
      className={`app-sidebar ${isOpen ? 'open' : 'collapsed'}`}
      style={{
        width: isOpen ? '270px' : '64px',
        minWidth: isOpen ? '270px' : '64px',
        backgroundColor: 'var(--bg-surface)',
        borderRight: '1px solid var(--border-light)',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        minHeight: 0,
        flexShrink: 0,
        overflow: 'hidden',
        transition: 'width 0.2s ease, min-width 0.2s ease',
        zIndex: 40,
        position: 'relative',
        userSelect: 'none',
      }}
      aria-label="Conversation and Workspace Navigation"
    >
      {/* Sidebar Header / New Chat */}
      <div style={{ padding: '0.85rem', borderBottom: '1px solid var(--border-light)', display: 'flex', flexDirection: 'column', gap: '0.5rem', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          {isOpen ? (
            <span style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)' }}>
              Conversations
            </span>
          ) : null}
          <button
            type="button"
            onClick={onToggleOpen}
            title={isOpen ? 'Collapse sidebar' : 'Expand sidebar'}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-muted)',
              cursor: 'pointer',
              padding: '0.3rem',
              borderRadius: 'var(--radius-sm)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              marginLeft: isOpen ? 'auto' : 'auto',
              marginRight: isOpen ? 0 : 'auto',
            }}
          >
            {isOpen ? <ChevronLeft size={16} /> : <ChevronRight size={16} />}
          </button>
        </div>

        <button
          type="button"
          onClick={onNewChat}
          className="btn-primary"
          style={{
            width: '100%',
            padding: isOpen ? '0.55rem 0.85rem' : '0.55rem 0',
            fontSize: '0.85rem',
            fontWeight: 600,
            display: 'flex',
            alignItems: 'center',
            justifyContent: isOpen ? 'flex-start' : 'center',
            gap: '0.5rem',
            borderRadius: 'var(--radius-md)',
          }}
          title="Start a new chat session"
        >
          <Plus size={16} />
          {isOpen ? <span>New Chat</span> : null}
        </button>
      </div>

      {/* Recent Sessions List */}
      <div style={{ flex: '1 1 0%', minHeight: 0, overflowY: 'auto', padding: '0.5rem 0.5rem' }}>
        {isOpen && sessions.length === 0 ? (
          <div style={{ padding: '1.5rem 0.5rem', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
            No recent conversations yet.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
            {sessions.map((sess) => {
              const isActive = sess.id === activeSessionId && !isLibraryActive;
              const displayTitle = sess.title || 'Untitled Conversation';

              return (
                <button
                  key={sess.id}
                  type="button"
                  onClick={() => onSelectSession(sess.id)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.6rem',
                    padding: isOpen ? '0.5rem 0.65rem' : '0.5rem 0',
                    justifyContent: isOpen ? 'flex-start' : 'center',
                    borderRadius: 'var(--radius-md)',
                    border: 'none',
                    backgroundColor: isActive ? 'var(--primary-light)' : 'transparent',
                    color: isActive ? 'var(--primary)' : 'var(--text-main)',
                    cursor: 'pointer',
                    textAlign: 'left',
                    width: '100%',
                    fontSize: '0.825rem',
                    fontWeight: isActive ? 600 : 400,
                    transition: 'background-color 0.15s ease',
                  }}
                  title={displayTitle}
                >
                  <MessageSquare size={16} style={{ flexShrink: 0, color: isActive ? 'var(--primary)' : 'var(--text-muted)' }} />
                  {isOpen && (
                    <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1, minWidth: 0 }}>
                      <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {displayTitle}
                      </div>
                      <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '0.1rem' }}>
                        {formatSessionTime(sess.updated_at || sess.created_at)}
                      </div>
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Secondary Navigation: Library & Artifacts */}
      <div style={{ padding: '0.65rem 0.5rem', borderTop: '1px solid var(--border-light)', flexShrink: 0 }}>
        <button
          type="button"
          onClick={onOpenLibrary}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.6rem',
            padding: isOpen ? '0.55rem 0.65rem' : '0.55rem 0',
            justifyContent: isOpen ? 'flex-start' : 'center',
            borderRadius: 'var(--radius-md)',
            border: 'none',
            backgroundColor: isLibraryActive ? 'var(--primary-light)' : 'transparent',
            color: isLibraryActive ? 'var(--primary)' : 'var(--text-secondary)',
            cursor: 'pointer',
            textAlign: 'left',
            width: '100%',
            fontSize: '0.825rem',
            fontWeight: isLibraryActive ? 600 : 500,
          }}
          title="View saved essays and writing artifacts"
        >
          <Library size={16} style={{ flexShrink: 0, color: isLibraryActive ? 'var(--primary)' : 'var(--text-muted)' }} />
          {isOpen && <span>Artifacts & Library</span>}
        </button>
      </div>

      {/* Model Status Pill */}
      {isOpen && (
        <div
          style={{
            padding: '0.65rem 0.85rem',
            borderTop: '1px solid var(--border-light)',
            backgroundColor: 'var(--bg-subtle)',
            fontSize: '0.72rem',
            color: 'var(--text-secondary)',
            display: 'flex',
            alignItems: 'center',
            gap: '0.45rem',
            flexShrink: 0,
          }}
        >
          <span
            style={{
              width: '7px',
              height: '7px',
              borderRadius: '50%',
              backgroundColor: '#10b981',
              display: 'inline-block',
              flexShrink: 0,
            }}
          />
          <Cpu size={12} style={{ color: 'var(--text-muted)' }} />
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {(() => {
              const p = providerInfo?.provider?.toLowerCase();
              if (p === 'nvidia' || p === 'nim') {
                return `Active model: NVIDIA NIM · ${providerInfo?.model || 'openai/gpt-oss-20b'}`;
              }
              if (p === 'litellm' || p === 'cloud') {
                const cloudModel = (providerInfo?.model || 'gpt-oss-20b').replace('openai/', '');
                return `Active model: OpenAI · ${cloudModel}`;
              }
              const m = providerInfo?.model || 'qwen2.5:1.5b';
              return `Active model: Ollama · ${m}`;
            })()}
          </span>
        </div>
      )}
    </aside>
  );
};
