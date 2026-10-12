import React, { useState, useEffect, useRef } from 'react';
import {
  Save,
  RotateCcw,
  Bookmark,
  History,
  Check,
  AlertCircle,
  FileCode,
  Eye,
  Loader2,
  ArrowLeft,
  Maximize2,
  Minimize2,
  Columns,
} from 'lucide-react';
import { apiClient } from '../api/client';
import type {
  WritingArtifactResponse,
  WritingArtifactVersionResponse,
  WritingArtifactVersionSummary,
} from '../api/types';
import { MarkdownEditor } from './MarkdownEditor';
import { HtmlPreview } from './HtmlPreview';
import { RevisionBar } from './RevisionBar';
import { SourcesDrawer } from './SourcesDrawer';
import { VersionHistoryDrawer } from './VersionHistoryDrawer';

interface WorkspaceProps {
  artifact: WritingArtifactResponse;
  onArtifactUpdated: (updatedArtifact: WritingArtifactResponse) => void;
  onBackToChat?: () => void;
  isExpanded?: boolean;
  onToggleExpand?: () => void;
}

export const Workspace: React.FC<WorkspaceProps> = ({
  artifact,
  onArtifactUpdated,
  onBackToChat,
  isExpanded = false,
  onToggleExpand,
}) => {
  // Current active version snapshot
  const [activeVersion, setActiveVersion] = useState<WritingArtifactVersionResponse>(
    artifact.latest_version
  );

  // Editor content and dirty state
  const [markdownContent, setMarkdownContent] = useState<string>(
    artifact.latest_version.markdown_content
  );
  const [htmlPreviewContent, setHtmlPreviewContent] = useState<string>(
    artifact.latest_version.html_content
  );
  const [liveWordCount, setLiveWordCount] = useState<number>(
    artifact.latest_version.word_count
  );
  const [isDirty, setIsDirty] = useState<boolean>(false);

  // UI state
  const [viewMode, setViewMode] = useState<'split' | 'editor' | 'preview'>('split');
  const [isSourcesOpen, setIsSourcesOpen] = useState<boolean>(false);
  const [isHistoryOpen, setIsHistoryOpen] = useState<boolean>(false);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [isRevising, setIsRevising] = useState<boolean>(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Version list
  const [versionsList, setVersionsList] = useState<WritingArtifactVersionSummary[]>([]);

  // Preview debounce timer
  const previewTimerRef = useRef<number | null>(null);

  // Load versions list
  const refreshVersionsList = async () => {
    const isUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(artifact.id);
    if (!isUuid) return;
    try {
      const history = await apiClient.getArtifactVersions(artifact.id);
      setVersionsList(history.versions);
    } catch (err: any) {
      console.warn('Could not load version history:', err);
    }
  };

  useEffect(() => {
    refreshVersionsList();
  }, [artifact.id]);

  // Update state when artifact prop updates from parent
  useEffect(() => {
    setActiveVersion(artifact.latest_version);
    setMarkdownContent(artifact.latest_version.markdown_content);
    setHtmlPreviewContent(artifact.latest_version.html_content);
    setLiveWordCount(artifact.latest_version.word_count);
    setIsDirty(false);
  }, [artifact.id, artifact.latest_version.version_number]);

  // Debounced live HTML preview when user edits Markdown
  const handleContentChange = (newContent: string) => {
    setMarkdownContent(newContent);
    const hasChanged = newContent !== activeVersion.markdown_content;
    setIsDirty(hasChanged);

    if (previewTimerRef.current) {
      clearTimeout(previewTimerRef.current);
    }

    if (hasChanged) {
      previewTimerRef.current = window.setTimeout(async () => {
        try {
          const previewResp = await apiClient.previewMarkdown(newContent);
          setHtmlPreviewContent(previewResp.html_content);
          setLiveWordCount(previewResp.word_count);
        } catch (err) {
          console.warn('Live preview failed:', err);
        }
      }, 400);
    } else {
      setHtmlPreviewContent(activeVersion.html_content);
      setLiveWordCount(activeVersion.word_count);
    }
  };

  // Save manual edit as a new immutable version
  const handleSaveManualVersion = async () => {
    if (isSaving || !isDirty) return;

    setIsSaving(true);
    setErrorMessage(null);
    setStatusMessage(null);

    try {
      const updatedArtifact = await apiClient.saveManualVersion(artifact.id, {
        markdown_content: markdownContent,
        note: `Manual edit saved at ${new Date().toLocaleTimeString()}`,
      });

      onArtifactUpdated(updatedArtifact);
      setActiveVersion(updatedArtifact.latest_version);
      const evalMeta = updatedArtifact.latest_version.eval_metadata;
      const isWordCountPass = evalMeta?.word_count_in_range ?? evalMeta?.word_count_check;
      if (isWordCountPass === false) {
        setStatusMessage(
          `Saved version v${updatedArtifact.latest_version.version_number}. Note: Body word count (${updatedArtifact.latest_version.word_count}) is outside target range.`
        );
      } else {
        setStatusMessage(`Saved new immutable version v${updatedArtifact.latest_version.version_number}!`);
      }
      refreshVersionsList();

      setTimeout(() => setStatusMessage(null), 5000);
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to save version.');
    } finally {
      setIsSaving(false);
    }
  };

  // Discard changes and revert to active version
  const handleDiscardChanges = () => {
    if (isDirty && !window.confirm('Discard all unsaved edits and reload the saved version?')) {
      return;
    }
    setMarkdownContent(activeVersion.markdown_content);
    setHtmlPreviewContent(activeVersion.html_content);
    setLiveWordCount(activeVersion.word_count);
    setIsDirty(false);
  };

  // Switch to an older or specific historical version
  const handleSelectHistoricalVersion = async (versionNumber: number) => {
    if (versionNumber === activeVersion.version_number) {
      setIsHistoryOpen(false);
      return;
    }

    if (isDirty && !window.confirm('You have unsaved changes. Switching versions will discard them. Continue?')) {
      return;
    }

    try {
      const specificVersion = await apiClient.getSpecificVersion(artifact.id, versionNumber);
      setActiveVersion(specificVersion);
      setMarkdownContent(specificVersion.markdown_content);
      setHtmlPreviewContent(specificVersion.html_content);
      setLiveWordCount(specificVersion.word_count);
      setIsDirty(false);
      setIsHistoryOpen(false);
    } catch (err: any) {
      setErrorMessage(`Cannot load version ${versionNumber}: ${err.message}`);
    }
  };

  // Handle AI Revision Success
  const handleRevisionSuccess = (updatedArtifact: WritingArtifactResponse) => {
    setIsRevising(false);
    onArtifactUpdated(updatedArtifact);
    setActiveVersion(updatedArtifact.latest_version);
    setMarkdownContent(updatedArtifact.latest_version.markdown_content);
    setHtmlPreviewContent(updatedArtifact.latest_version.html_content);
    setLiveWordCount(updatedArtifact.latest_version.word_count);
    setIsDirty(false);
    setStatusMessage(`AI revision generated version v${updatedArtifact.latest_version.version_number}!`);
    refreshVersionsList();
    setTimeout(() => setStatusMessage(null), 5000);
  };

  return (
    <div className="workspace-container">
      {/* Workspace Header Toolbar */}
      <div className="workspace-toolbar">
        <div className="workspace-doc-info">
          <span className="doc-title" title={artifact.title}>
            {artifact.title}
          </span>
          <span className="version-chip">v{activeVersion.version_number}</span>
          <div className="word-count-badge">
            <strong>{liveWordCount}</strong> words
          </div>

          {isDirty ? (
            <span className="unsaved-pill" title="Unsaved manual changes in editor">
              ● Unsaved edits
            </span>
          ) : (
            <span className="saved-pill">
              <Check size={13} />
              Saved
            </span>
          )}

          {/* Quality Acceptance State Pill */}
          {(() => {
            const isPass = Boolean(
              activeVersion.eval_metadata?.passed ??
              activeVersion.eval_metadata?.passes_all_checks ??
              false
            );
            if (isPass) {
              return (
                <span className="eval-pass-pill" title="Deterministic acceptance checks passed">
                  <Check size={11} /> Accepted
                </span>
              );
            }
            return (
              <span
                className="eval-fail-pill"
                title="Word count or structural criteria not met. Click to view details."
                onClick={() => setIsHistoryOpen(true)}
                style={{ cursor: 'pointer' }}
              >
                <AlertCircle size={11} /> Out of Target
              </span>
            );
          })()}
        </div>

        {/* View Mode Switcher (Split, Editor only, HTML Preview only) */}
        <div className="workspace-view-modes" style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
          <button
            type="button"
            className={`btn-secondary ${viewMode === 'split' ? 'active' : ''}`}
            style={{ padding: '0.35rem 0.65rem', fontSize: '0.75rem', display: 'inline-flex', alignItems: 'center', gap: '0.3rem' }}
            onClick={() => setViewMode('split')}
            title="Side-by-side Editor and HTML Preview"
          >
            <Columns size={13} />
            <span>Split</span>
          </button>
          <button
            type="button"
            className={`btn-secondary ${viewMode === 'editor' ? 'active' : ''}`}
            style={{ padding: '0.35rem 0.65rem', fontSize: '0.75rem', display: 'inline-flex', alignItems: 'center', gap: '0.3rem' }}
            onClick={() => setViewMode('editor')}
            title="Full-width Markdown Source Editor"
          >
            <FileCode size={13} />
            <span>Editor</span>
          </button>
          <button
            type="button"
            className={`btn-secondary ${viewMode === 'preview' ? 'active' : ''}`}
            style={{ padding: '0.35rem 0.65rem', fontSize: '0.75rem', display: 'inline-flex', alignItems: 'center', gap: '0.3rem' }}
            onClick={() => setViewMode('preview')}
            title="Full-width Sandboxed HTML Preview"
          >
            <Eye size={13} />
            <span>HTML Preview</span>
          </button>
        </div>

        {/* Actions */}
        <div className="workspace-actions">
          {onToggleExpand && (
            <button
              type="button"
              className="btn-secondary"
              style={{ padding: '0.45rem 0.75rem', fontSize: '0.8rem', display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}
              onClick={onToggleExpand}
              title={isExpanded ? 'Restore split view beside chat' : 'Expand to full workspace'}
            >
              {isExpanded ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
              <span>{isExpanded ? 'Split beside Chat' : 'Expand'}</span>
            </button>
          )}

          {onBackToChat && (
            <button
              type="button"
              className="btn-secondary"
              style={{ padding: '0.45rem 0.75rem', fontSize: '0.8rem', display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}
              onClick={onBackToChat}
              title="Return to conversation"
            >
              <ArrowLeft size={14} />
              <span>Back to Chat</span>
            </button>
          )}

          {isDirty && (
            <button
              type="button"
              className="btn-secondary"
              style={{ padding: '0.45rem 0.75rem', fontSize: '0.8rem' }}
              onClick={handleDiscardChanges}
              disabled={isSaving}
              title="Discard unsaved changes"
            >
              <RotateCcw size={14} />
              <span>Discard</span>
            </button>
          )}

          <button
            type="button"
            className="btn-primary"
            style={{ padding: '0.45rem 0.85rem', fontSize: '0.8rem' }}
            onClick={handleSaveManualVersion}
            disabled={!isDirty || isSaving}
            title="Save as a new immutable version"
          >
            {isSaving ? (
              <>
                <Loader2 size={14} className="animate-spin" />
                <span>Saving...</span>
              </>
            ) : (
              <>
                <Save size={14} />
                <span>Save New Version</span>
              </>
            )}
          </button>

          <button
            type="button"
            className="btn-secondary"
            style={{ padding: '0.45rem 0.75rem', fontSize: '0.8rem' }}
            onClick={() => setIsSourcesOpen(true)}
            title="Inspect Grounded Podcast Citations"
          >
            <Bookmark size={14} />
            <span>Sources ({activeVersion.sources?.length ?? 0})</span>
          </button>

          <button
            type="button"
            className="btn-secondary"
            style={{ padding: '0.45rem 0.75rem', fontSize: '0.8rem' }}
            onClick={() => setIsHistoryOpen(true)}
            title="Version History & Quality Evaluation"
          >
            <History size={14} />
            <span>History</span>
          </button>
        </div>
      </div>

      {/* Quality Gate Diagnostic Banner for Drafts Needing Revision */}
      {(() => {
        const isPass = Boolean(
          activeVersion.eval_metadata?.passed ??
          activeVersion.eval_metadata?.passes_all_checks ??
          false
        );
        if (isPass) return null;
        return (
          <div
            data-testid="quality-diagnostic-banner"
            style={{
              background: 'rgba(239, 68, 68, 0.08)',
              borderBottom: '1px solid rgba(239, 68, 68, 0.25)',
              color: '#b91c1c',
              padding: '0.6rem 1.25rem',
              fontSize: '0.8rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.3rem',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 600 }}>
              <AlertCircle size={15} />
              <span>Needs Revision — Quality Criteria Notice</span>
              <span style={{ fontWeight: 400, marginLeft: 'auto', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                Draft persisted & accessible for editing and AI revision
              </span>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '1rem', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
              <span>
                <strong>Word count:</strong> {activeVersion.eval_metadata?.body_word_count ?? liveWordCount} words
                (target: {activeVersion.writing_brief?.target_word_count ?? 1250}
                {activeVersion.eval_metadata?.acceptable_range ? `, acceptable: ${activeVersion.eval_metadata.acceptable_range[0]}–${activeVersion.eval_metadata.acceptable_range[1]}` : ''})
              </span>
              {activeVersion.eval_metadata?.feedback && activeVersion.eval_metadata.feedback.length > 0 && (
                <span>
                  <strong>Feedback:</strong> {activeVersion.eval_metadata.feedback.join('; ')}
                </span>
              )}
              <span>
                <strong>Citations:</strong> {activeVersion.sources?.length ?? 0} grounded podcast source(s)
              </span>
            </div>
          </div>
        );
      })()}

      {/* Status or Error Banners */}
      {statusMessage && (
        <div
          style={{
            background: 'var(--success-light)',
            color: 'var(--success)',
            padding: '0.5rem 1.25rem',
            fontSize: '0.825rem',
            borderBottom: '1px solid var(--success-border)',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
          }}
        >
          <Check size={14} />
          <span>{statusMessage}</span>
        </div>
      )}

      {errorMessage && (
        <div
          style={{
            background: 'var(--danger-light)',
            color: 'var(--danger)',
            padding: '0.5rem 1.25rem',
            fontSize: '0.825rem',
            borderBottom: '1px solid var(--danger-border)',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
          }}
        >
          <AlertCircle size={14} />
          <span style={{ flex: 1 }}>{errorMessage}</span>
          <button
            type="button"
            style={{ textDecoration: 'underline', fontSize: '0.75rem', color: 'inherit' }}
            onClick={() => setErrorMessage(null)}
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Panes (Controlled by viewMode) */}
      <div className={`workspace-panes mode-${viewMode}`}>
        {/* Left Pane: Markdown Editor */}
        {(viewMode === 'split' || viewMode === 'editor') && (
          <section
            className={`pane-editor ${viewMode === 'editor' ? 'active' : ''}`}
            aria-label="Markdown Editor Panel"
            style={{ flex: viewMode === 'editor' ? '1 1 100%' : '1 1 50%' }}
          >
            <div className="pane-header">
              <span>Markdown Source</span>
              <span style={{ fontSize: '0.75rem', fontWeight: 400 }}>
                {isDirty ? 'Live draft' : `Version ${activeVersion.version_number}`}
              </span>
            </div>

            <MarkdownEditor
              content={markdownContent}
              onChange={handleContentChange}
              onSave={handleSaveManualVersion}
              disabled={isSaving || isRevising}
            />
          </section>
        )}

        {/* Right Pane: Sandboxed HTML Preview */}
        {(viewMode === 'split' || viewMode === 'preview') && (
          <section
            className={`pane-preview ${viewMode === 'preview' ? 'active' : ''}`}
            aria-label="Rendered Preview Panel"
            style={{ flex: viewMode === 'preview' ? '1 1 100%' : '1 1 50%' }}
          >
            <div className="pane-header">
              <span>Sanitized HTML Preview</span>
              <span style={{ fontSize: '0.75rem', fontWeight: 400 }}>
                {isDirty ? 'Live rendered preview' : 'Persisted preview'}
              </span>
            </div>

            <HtmlPreview htmlContent={htmlPreviewContent} />
          </section>
        )}
      </div>

      {/* Revision Prompt Bar */}
      <RevisionBar
        artifactId={artifact.id}
        isRevising={isRevising}
        onRevisionStart={() => {
          setIsRevising(true);
          setErrorMessage(null);
        }}
        onRevisionSuccess={handleRevisionSuccess}
        onRevisionError={(err) => {
          setIsRevising(false);
          setErrorMessage(err);
        }}
      />

      {/* Drawers */}
      <SourcesDrawer
        isOpen={isSourcesOpen}
        onClose={() => setIsSourcesOpen(false)}
        sources={activeVersion.sources || []}
        versionNumber={activeVersion.version_number}
      />

      <VersionHistoryDrawer
        isOpen={isHistoryOpen}
        onClose={() => setIsHistoryOpen(false)}
        versions={versionsList}
        currentVersionNumber={activeVersion.version_number}
        evalMetadata={activeVersion.eval_metadata || {}}
        onSelectVersion={handleSelectHistoricalVersion}
      />
    </div>
  );
};
