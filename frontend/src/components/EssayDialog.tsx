import React, { useState } from 'react';
import { X, Sparkles, AlertCircle, Loader2 } from 'lucide-react';
import { apiClient, ApiError } from '../api/client';
import type { EssayJobResponse, EssayTone, WritingArtifactResponse, WritingBriefRequest } from '../api/types';

interface EssayDialogProps {
  initialTopic: string;
  sessionId?: string | null;
  isOpen: boolean;
  onClose: () => void;
  onEssayCreated: (artifact: WritingArtifactResponse) => void;
}

export const EssayDialog: React.FC<EssayDialogProps> = ({
  initialTopic,
  sessionId,
  isOpen,
  onClose,
  onEssayCreated,
}) => {
  const [topic, setTopic] = useState<string>(initialTopic || '');
  const [targetWordCount, setTargetWordCount] = useState<number>(1250);
  const [tone, setTone] = useState<EssayTone>('conversational');
  const [audience, setAudience] = useState<string>('Founders and Product Managers');
  const [purpose, setPurpose] = useState<string>('Explain actionable frameworks and takeaways');
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [pollJob, setPollJob] = useState<EssayJobResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!topic.trim()) return;

    setIsSubmitting(true);
    setErrorMessage(null);
    setPollJob(null);

    const brief: WritingBriefRequest = {
      topic: topic.trim(),
      target_word_count: targetWordCount,
      tone,
      audience: audience.trim() || undefined,
      purpose: purpose.trim() || undefined,
      session_id: sessionId || null,
      include_outline: true,
    };

    try {
      const jobResp = await apiClient.submitEssay(brief);
      setPollJob(jobResp);

      // Poll until terminal state
      const terminalJob = await pollUntilComplete(jobResp.job_id);
      setPollJob(terminalJob);

      if (terminalJob.artifact_id) {
        // If an artifact was persisted (either passed or with quality warnings), open it in Workspace
        try {
          const artifact = await apiClient.getArtifact(terminalJob.artifact_id);
          onEssayCreated(artifact);
          onClose();
          return;
        } catch (fetchErr) {
          console.warn('Could not fetch persisted artifact:', fetchErr);
        }
      }

      if (terminalJob.status === 'failed') {
        const rawErr = terminalJob.error || '';
        let msg = 'The essay generation failed before producing a usable artifact.';
        if (rawErr.toLowerCase().includes('model is unavailable') || rawErr.toLowerCase().includes('not found')) {
          msg = 'The selected model is unavailable. Check the provider configuration.';
        } else if (rawErr.toLowerCase().includes('cloud provider rejected') || rawErr.toLowerCase().includes('credentials') || rawErr.toLowerCase().includes('authentication') || rawErr.toLowerCase().includes('401') || rawErr.toLowerCase().includes('403')) {
          msg = 'The cloud provider rejected the request. Verify model access and credentials.';
        } else if (rawErr.toLowerCase().includes('timed out') || rawErr.toLowerCase().includes('timeout')) {
          msg = 'Essay generation timed out. Please retry.';
        } else if (rawErr.toLowerCase().includes('worker is unavailable') || rawErr.toLowerCase().includes('writing worker')) {
          msg = 'The writing worker is unavailable. Please try again shortly.';
        } else if (rawErr.toLowerCase().includes('quality evaluation') || rawErr.toLowerCase().includes('word count') || rawErr.toLowerCase().includes('citation')) {
          msg = `The essay did not meet the required quality checks: ${rawErr}`;
        } else if (rawErr) {
          msg = rawErr;
        }
        setErrorMessage(`${msg} (Job ID: ${terminalJob.job_id})`);
      }
    } catch (err: any) {
      if (err instanceof ApiError) {
        const detailMsg = err.details?.message || err.message;
        setErrorMessage(`${detailMsg} (Code: ${err.code}, Status: ${err.status})`);
      } else {
        setErrorMessage(err.message || 'An unexpected error occurred while generating the essay.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const pollUntilComplete = async (jobId: string, intervalMs: number = 2000): Promise<EssayJobResponse> => {
    const maxAttempts = 180;

    for (let i = 0; i < maxAttempts; i++) {
      const status = await apiClient.getJobStatus(jobId);
      setPollJob(status);

      if (status.status === 'completed' || status.status === 'failed') {
        return status;
      }
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
    throw new Error(`Essay generation timed out in queue after ${maxAttempts * (intervalMs / 1000)}s. Please retry or check recent artifacts in Library.`);
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(15, 23, 42, 0.6)',
        backdropFilter: 'blur(3px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
        padding: '1rem',
      }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="essay-dialog-title"
    >
      <div
        style={{
          backgroundColor: 'var(--bg-surface)',
          borderRadius: 'var(--radius-lg)',
          border: '1px solid var(--border-medium)',
          boxShadow: 'var(--shadow-lg)',
          width: '100%',
          maxWidth: '560px',
          maxHeight: '90vh',
          overflowY: 'auto',
          padding: '1.75rem',
          position: 'relative',
        }}
      >
        <button
          type="button"
          onClick={onClose}
          disabled={isSubmitting}
          style={{
            position: 'absolute',
            top: '1.25rem',
            right: '1.25rem',
            background: 'none',
            border: 'none',
            color: 'var(--text-muted)',
            cursor: 'pointer',
            padding: '0.25rem',
          }}
          aria-label="Close dialog"
        >
          <X size={20} />
        </button>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
          <div
            style={{
              backgroundColor: 'var(--primary-light)',
              color: 'var(--primary)',
              borderRadius: 'var(--radius-sm)',
              padding: '0.35rem',
              display: 'flex',
            }}
          >
            <Sparkles size={18} />
          </div>
          <h2 id="essay-dialog-title" style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--text-main)', margin: 0 }}>
            Create Essay
          </h2>
        </div>

        <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginBottom: '1.25rem', lineHeight: 1.5 }}>
          Transforms conversation takeaways into a grounded, publication-grade essay with mandatory quality criteria.
        </p>

        {errorMessage && (
          <div
            style={{
              padding: '0.75rem 1rem',
              borderRadius: 'var(--radius-md)',
              backgroundColor: 'var(--danger-light)',
              border: '1px solid var(--danger-border)',
              color: 'var(--danger)',
              fontSize: '0.85rem',
              marginBottom: '1rem',
              display: 'flex',
              alignItems: 'flex-start',
              gap: '0.5rem',
            }}
          >
            <AlertCircle size={16} style={{ flexShrink: 0, marginTop: '0.1rem' }} />
            <div>
              <strong>Generation Notice: </strong>
              {errorMessage}
            </div>
          </div>
        )}

        {isSubmitting && pollJob && (
          <div
            style={{
              padding: '1rem',
              borderRadius: 'var(--radius-md)',
              backgroundColor: 'var(--primary-light)',
              border: '1px solid var(--primary-border)',
              marginBottom: '1.25rem',
              display: 'flex',
              flexDirection: 'column',
              gap: '0.5rem',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--primary)', fontWeight: 600, fontSize: '0.875rem' }}>
              <Loader2 size={16} className="spin-animation" />
              <span>{pollJob.stage || 'Processing essay job...'}</span>
            </div>
            <p style={{ margin: 0, fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
              Status: <span style={{ textTransform: 'capitalize' }}>{pollJob.status}</span> · Elapsed: {pollJob.elapsed_seconds ? `${pollJob.elapsed_seconds.toFixed(1)}s` : '0s'}
            </p>
          </div>
        )}

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div>
            <label htmlFor="essay-topic" style={{ display: 'block', fontSize: '0.825rem', fontWeight: 600, color: 'var(--text-main)', marginBottom: '0.35rem' }}>
              Essay Topic or Core Concept *
            </label>
            <input
              id="essay-topic"
              type="text"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              disabled={isSubmitting}
              required
              placeholder="e.g., Rahul Vohra on the Superhuman PMF Engine"
              style={{
                width: '100%',
                padding: '0.6rem 0.75rem',
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--border-medium)',
                fontSize: '0.9rem',
                color: 'var(--text-main)',
                backgroundColor: 'var(--bg-surface)',
              }}
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
            <div>
              <label htmlFor="essay-target-words" style={{ display: 'block', fontSize: '0.825rem', fontWeight: 600, color: 'var(--text-main)', marginBottom: '0.35rem' }}>
                Target Word Count
              </label>
              <select
                id="essay-target-words"
                value={targetWordCount}
                onChange={(e) => setTargetWordCount(Number(e.target.value))}
                disabled={isSubmitting}
                style={{
                  width: '100%',
                  padding: '0.6rem 0.75rem',
                  borderRadius: 'var(--radius-md)',
                  border: '1px solid var(--border-medium)',
                  fontSize: '0.875rem',
                  backgroundColor: 'var(--bg-surface)',
                }}
              >
                <option value={1250}>1,250 words (Standard Ship 30 for 30)</option>
                <option value={1000}>1,000 words (Condensed)</option>
                <option value={1500}>1,500 words (Comprehensive)</option>
                <option value={800}>800 words (Atomic)</option>
              </select>
            </div>

            <div>
              <label htmlFor="essay-tone" style={{ display: 'block', fontSize: '0.825rem', fontWeight: 600, color: 'var(--text-main)', marginBottom: '0.35rem' }}>
                Editorial Tone
              </label>
              <select
                id="essay-tone"
                value={tone}
                onChange={(e) => setTone(e.target.value as EssayTone)}
                disabled={isSubmitting}
                style={{
                  width: '100%',
                  padding: '0.6rem 0.75rem',
                  borderRadius: 'var(--radius-md)',
                  border: '1px solid var(--border-medium)',
                  fontSize: '0.875rem',
                  backgroundColor: 'var(--bg-surface)',
                }}
              >
                <option value="conversational">Conversational</option>
                <option value="educational">Educational</option>
                <option value="analytical">Analytical</option>
                <option value="persuasive">Persuasive</option>
              </select>
            </div>
          </div>

          <div>
            <label htmlFor="essay-audience" style={{ display: 'block', fontSize: '0.825rem', fontWeight: 600, color: 'var(--text-main)', marginBottom: '0.35rem' }}>
              Target Audience
            </label>
            <input
              id="essay-audience"
              type="text"
              value={audience}
              onChange={(e) => setAudience(e.target.value)}
              disabled={isSubmitting}
              placeholder="e.g., Early-stage founders"
              style={{
                width: '100%',
                padding: '0.55rem 0.75rem',
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--border-medium)',
                fontSize: '0.875rem',
              }}
            />
          </div>

          <div>
            <label htmlFor="essay-purpose" style={{ display: 'block', fontSize: '0.825rem', fontWeight: 600, color: 'var(--text-main)', marginBottom: '0.35rem' }}>
              Core Purpose
            </label>
            <input
              id="essay-purpose"
              type="text"
              value={purpose}
              onChange={(e) => setPurpose(e.target.value)}
              disabled={isSubmitting}
              placeholder="e.g., Provide a step-by-step checklist"
              style={{
                width: '100%',
                padding: '0.55rem 0.75rem',
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--border-medium)',
                fontSize: '0.875rem',
              }}
            />
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '0.5rem' }}>
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              style={{
                padding: '0.6rem 1rem',
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--border-medium)',
                backgroundColor: 'transparent',
                color: 'var(--text-secondary)',
                fontWeight: 600,
                fontSize: '0.875rem',
                cursor: 'pointer',
              }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting || !topic.trim()}
              className="btn-primary"
              style={{
                padding: '0.6rem 1.25rem',
                borderRadius: 'var(--radius-md)',
                fontSize: '0.875rem',
                fontWeight: 600,
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.45rem',
              }}
            >
              {isSubmitting ? (
                <>
                  <Loader2 size={16} className="spin-animation" />
                  <span>Drafting Essay...</span>
                </>
              ) : (
                <>
                  <Sparkles size={16} />
                  <span>Create Essay</span>
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
