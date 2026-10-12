import React, { useState } from 'react';
import { MessageSquare, Library, Sparkles, Menu, ArrowLeft, Loader2, Play } from 'lucide-react';
import type { LLMSettingsResponse, ModelConfigResponse } from '../api/types';
import { apiClient } from '../api/client';

export interface HeaderProps {
  currentView: 'chat' | 'library' | 'workspace';
  onSelectView: (view: 'chat' | 'library' | 'workspace') => void;
  onToggleSidebar?: () => void;
  hasActiveArtifact: boolean;
  onBackToChat?: () => void;
  llmSettings?: LLMSettingsResponse | null;
  onSwitchProvider?: (provider: 'ollama' | 'nvidia', model?: string) => Promise<void>;
  onTestProvider?: (provider: string) => Promise<{ connected: boolean; message: string; elapsed_seconds?: number }>;
  modelConfig?: ModelConfigResponse | null;
  onSwitchModel?: (provider: 'ollama' | 'litellm' | 'nvidia', model?: string) => void;
}

export const Header: React.FC<HeaderProps> = ({
  currentView,
  onSelectView,
  onToggleSidebar,
  hasActiveArtifact,
  onBackToChat,
  llmSettings,
  onSwitchProvider,
  onTestProvider,
  modelConfig,
  onSwitchModel,
}) => {
  const [isSwitching, setIsSwitching] = useState<boolean>(false);
  const [isTesting, setIsTesting] = useState<boolean>(false);
  const [testFeedback, setTestFeedback] = useState<{ success: boolean; message: string } | null>(null);
  const [errorFeedback, setErrorFeedback] = useState<string | null>(null);

  // Determine active provider & model from llmSettings or fallback modelConfig
  const activeProvider = (llmSettings?.active_provider || modelConfig?.active_provider || 'ollama').toLowerCase();
  const isNvidia = activeProvider === 'nvidia' || activeProvider === 'nim';
  const isCloud = isNvidia || activeProvider === 'litellm' || activeProvider === 'cloud';

  // Status indicator styling
  let statusDotColor = '#10b981'; // default green
  let statusDotTitle = 'Ollama local inference available';

  if (isCloud) {
    const nvidiaInfo = llmSettings?.providers?.find((p) => p.id === 'nvidia');
    if (nvidiaInfo) {
      if (nvidiaInfo.status === 'connected') {
        statusDotColor = '#10b981';
        statusDotTitle = 'NVIDIA NIM cloud connected';
      } else if (nvidiaInfo.status === 'configured') {
        statusDotColor = '#3b82f6';
        statusDotTitle = 'NVIDIA NIM configured with API key';
      } else if (nvidiaInfo.status === 'not_configured') {
        statusDotColor = '#94a3b8';
        statusDotTitle = 'NVIDIA NIM API key not configured';
      } else {
        statusDotColor = '#ef4444';
        statusDotTitle = `NVIDIA NIM unavailable: ${nvidiaInfo.status_message || 'unreachable'}`;
      }
    } else {
      statusDotColor = '#3b82f6';
      statusDotTitle = 'Cloud provider active';
    }
  }

  const handleProviderSelect = async (newVal: string) => {
    const targetProvider: 'ollama' | 'nvidia' = newVal.startsWith('ollama') ? 'ollama' : 'nvidia';
    if (targetProvider === (isCloud ? 'nvidia' : 'ollama')) return;

    setIsSwitching(true);
    setErrorFeedback(null);
    setTestFeedback(null);

    try {
      if (onSwitchProvider) {
        await onSwitchProvider(targetProvider);
      } else if (onSwitchModel) {
        onSwitchModel(targetProvider);
      }
    } catch (err: any) {
      const msg = err.message || (typeof err.details === 'object' && err.details?.message) || 'Failed to switch provider';
      setErrorFeedback(msg);
      setTimeout(() => setErrorFeedback(null), 6000);
    } finally {
      setIsSwitching(false);
    }
  };

  const handleRunTest = async () => {
    setIsTesting(true);
    setTestFeedback(null);
    setErrorFeedback(null);

    try {
      let res: { connected: boolean; message: string; elapsed_seconds?: number };
      if (onTestProvider) {
        res = await onTestProvider(activeProvider);
      } else {
        const provToTest = isCloud ? 'nvidia' : 'ollama';
        res = await apiClient.testLLMConnection({ provider: provToTest });
      }

      if (res.connected) {
        setTestFeedback({
          success: true,
          message: `Connected (${res.elapsed_seconds ? res.elapsed_seconds.toFixed(2) + 's' : 'OK'})`,
        });
      } else {
        setTestFeedback({
          success: false,
          message: res.message || 'Connection failed',
        });
      }
    } catch (err: any) {
      setTestFeedback({
        success: false,
        message: err.message || 'Connection test failed',
      });
    } finally {
      setIsTesting(false);
      setTimeout(() => setTestFeedback(null), 5000);
    }
  };

  const showSelector = Boolean(llmSettings || modelConfig);

  return (
    <header className="app-header" style={{ height: '60px', flexShrink: 0, width: '100%', minWidth: 0, padding: '0 1.25rem', borderBottom: '1px solid var(--border-light)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', backgroundColor: 'var(--bg-surface)' }}>
      <div className="brand-section" style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        {onToggleSidebar && (
          <button
            type="button"
            onClick={onToggleSidebar}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              padding: '0.35rem',
              borderRadius: 'var(--radius-sm)',
              display: 'flex',
              alignItems: 'center',
            }}
            aria-label="Toggle sidebar"
          >
            <Menu size={18} />
          </button>
        )}

        <div
          className="brand-logo"
          aria-hidden="true"
          style={{
            width: '32px',
            height: '32px',
            borderRadius: '8px',
            backgroundColor: 'var(--primary-light)',
            color: 'var(--primary)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <Sparkles size={18} />
        </div>

        <div>
          <span className="brand-title" style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--text-main)' }}>
            The Lenny Growth Assistant
          </span>
          <span
            className="brand-badge"
            style={{
              marginLeft: '0.5rem',
              fontSize: '0.7rem',
              fontWeight: 600,
              padding: '0.15rem 0.45rem',
              borderRadius: 'var(--radius-sm)',
              backgroundColor: 'var(--bg-subtle)',
              color: 'var(--text-secondary)',
            }}
          >
            {hasActiveArtifact && currentView === 'workspace' ? 'Artifact Active' : 'Podcast Intelligence'}
          </span>
        </div>
      </div>

      {/* Real Runtime Model Selector & Status Controls */}
      {showSelector && (
        <div
          className="model-switcher-control"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.45rem',
            backgroundColor: 'var(--bg-subtle)',
            border: '1px solid var(--border-medium)',
            borderRadius: 'var(--radius-md)',
            padding: '0.3rem 0.65rem',
            fontSize: '0.8rem',
          }}
        >
          <span
            title={statusDotTitle}
            style={{
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              backgroundColor: statusDotColor,
              display: 'inline-block',
              flexShrink: 0,
            }}
          />
          <span style={{ fontWeight: 600, color: 'var(--text-secondary)' }}>
            Model:
          </span>

          <select
            data-testid="model-selector-select"
            value={isCloud ? 'nvidia' : 'ollama'}
            disabled={isSwitching}
            onChange={(e) => handleProviderSelect(e.target.value)}
            style={{
              border: 'none',
              backgroundColor: 'transparent',
              fontWeight: 600,
              color: 'var(--text-main)',
              fontSize: '0.8rem',
              cursor: isSwitching ? 'wait' : 'pointer',
              outline: 'none',
              padding: '0.1rem 0.2rem',
            }}
            aria-label="Active inference model selector"
          >
            <option value="ollama">
              Ollama · qwen2.5:1.5b
            </option>
            <option value="nvidia">
              NVIDIA NIM · openai/gpt-oss-20b
            </option>
          </select>

          {/* Local vs Cloud Badge */}
          <span
            data-testid="model-category-badge"
            style={{
              fontSize: '0.68rem',
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: '0.04em',
              padding: '0.12rem 0.4rem',
              borderRadius: 'var(--radius-sm)',
              backgroundColor: isCloud ? 'rgba(59, 130, 246, 0.12)' : 'rgba(16, 185, 129, 0.12)',
              color: isCloud ? '#2563eb' : '#059669',
              border: `1px solid ${isCloud ? 'rgba(59, 130, 246, 0.25)' : 'rgba(16, 185, 129, 0.25)'}`,
              userSelect: 'none',
            }}
          >
            {isCloud ? 'Cloud' : 'Local'}
          </span>

          {/* Explicit Connection Test Button */}
          <button
            type="button"
            data-testid="model-test-btn"
            onClick={handleRunTest}
            disabled={isTesting || isSwitching}
            style={{
              background: 'none',
              border: '1px solid var(--border-medium)',
              borderRadius: 'var(--radius-sm)',
              padding: '0.15rem 0.45rem',
              fontSize: '0.72rem',
              fontWeight: 600,
              color: 'var(--text-secondary)',
              cursor: isTesting ? 'wait' : 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '0.25rem',
              marginLeft: '0.2rem',
            }}
            title={`Test live connection to ${isCloud ? 'NVIDIA NIM' : 'Ollama'}`}
          >
            {isTesting ? <Loader2 size={11} className="spin-animation" /> : <Play size={10} />}
            <span>{isTesting ? 'Testing' : 'Test'}</span>
          </button>

          {/* Test feedback */}
          {testFeedback && (
            <span
              data-testid="model-test-result"
              style={{
                fontSize: '0.72rem',
                fontWeight: 600,
                color: testFeedback.success ? '#059669' : '#dc2626',
                backgroundColor: testFeedback.success ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                border: `1px solid ${testFeedback.success ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`,
                padding: '0.12rem 0.35rem',
                borderRadius: 'var(--radius-sm)',
                maxWidth: '180px',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
              title={testFeedback.message}
            >
              {testFeedback.message}
            </span>
          )}

          {/* Error feedback banner */}
          {errorFeedback && (
            <span
              data-testid="model-error-banner"
              style={{
                fontSize: '0.72rem',
                fontWeight: 600,
                color: '#dc2626',
                backgroundColor: 'rgba(239, 68, 68, 0.1)',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                padding: '0.12rem 0.35rem',
                borderRadius: 'var(--radius-sm)',
                maxWidth: '220px',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
              title={errorFeedback}
            >
              {errorFeedback}
            </span>
          )}
        </div>
      )}

      <nav className="nav-tabs" aria-label="Main Navigation" style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
        <button
          type="button"
          className={`nav-btn ${currentView === 'chat' ? 'active' : ''}`}
          onClick={() => onSelectView('chat')}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '0.4rem',
            padding: '0.45rem 0.85rem',
            borderRadius: 'var(--radius-md)',
            border: 'none',
            backgroundColor: currentView === 'chat' ? 'var(--primary-light)' : 'transparent',
            color: currentView === 'chat' ? 'var(--primary)' : 'var(--text-secondary)',
            fontWeight: currentView === 'chat' ? 600 : 500,
            fontSize: '0.85rem',
            cursor: 'pointer',
          }}
        >
          <MessageSquare size={16} />
          <span>Chat</span>
        </button>

        {hasActiveArtifact && (
          <button
            type="button"
            className={`nav-btn ${currentView === 'workspace' ? 'active' : ''}`}
            onClick={() => onSelectView('workspace')}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '0.4rem',
              padding: '0.45rem 0.85rem',
              borderRadius: 'var(--radius-md)',
              border: 'none',
              backgroundColor: currentView === 'workspace' ? 'var(--primary-light)' : 'transparent',
              color: currentView === 'workspace' ? 'var(--primary)' : 'var(--text-secondary)',
              fontWeight: currentView === 'workspace' ? 600 : 500,
              fontSize: '0.85rem',
              cursor: 'pointer',
            }}
          >
            <Sparkles size={16} />
            <span>Workspace</span>
          </button>
        )}

        <button
          type="button"
          className={`nav-btn ${currentView === 'library' ? 'active' : ''}`}
          onClick={() => onSelectView('library')}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '0.4rem',
            padding: '0.45rem 0.85rem',
            borderRadius: 'var(--radius-md)',
            border: 'none',
            backgroundColor: currentView === 'library' ? 'var(--primary-light)' : 'transparent',
            color: currentView === 'library' ? 'var(--primary)' : 'var(--text-secondary)',
            fontWeight: currentView === 'library' ? 600 : 500,
            fontSize: '0.85rem',
            cursor: 'pointer',
          }}
        >
          <Library size={16} />
          <span>Artifacts & Library</span>
        </button>
      </nav>

      <div>
        {currentView === 'workspace' && onBackToChat ? (
          <button
            type="button"
            className="btn-secondary"
            onClick={onBackToChat}
            style={{
              padding: '0.45rem 0.85rem',
              fontSize: '0.825rem',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '0.35rem',
              borderRadius: 'var(--radius-md)',
              border: '1px solid var(--border-medium)',
              backgroundColor: 'var(--bg-surface)',
              color: 'var(--text-main)',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            <ArrowLeft size={14} />
            <span>Return to Chat</span>
          </button>
        ) : null}
      </div>
    </header>
  );
};
