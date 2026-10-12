import React, { useState, useEffect, useRef } from 'react';
import { Sparkles, Loader2, AlertCircle, RefreshCw, Clock, Eye } from 'lucide-react';
import { apiClient } from '../api/client';
import type { EssayJobResponse, EssayTone, WritingArtifactResponse, WritingBriefRequest } from '../api/types';

interface EssayComposerProps {
  onEssayGenerated: (artifact: WritingArtifactResponse) => void;
}

export const EssayComposer: React.FC<EssayComposerProps> = ({ onEssayGenerated }) => {
  // Form State
  const [topic, setTopic] = useState('');
  const [audience, setAudience] = useState('Product managers, founders, and growth leaders');
  const [purpose, setPurpose] = useState('Provide an actionable framework and strategic breakdown grounded in podcast insights.');
  const [centralThesis, setCentralThesis] = useState('');
  const [tone, setTone] = useState<EssayTone>('analytical');
  const [targetWordCount, setTargetWordCount] = useState(1250);
  const [additionalInstructions, setAdditionalInstructions] = useState('');

  // Execution & Job State
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [failedArtifactId, setFailedArtifactId] = useState<string | null>(null);
  const [activeJob, setActiveJob] = useState<EssayJobResponse | null>(null);

  const pollIntervalRef = useRef<number | null>(null);

  // Clear polling on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, []);

  const handleStartPolling = (jobId: string) => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
    }

    pollIntervalRef.current = window.setInterval(async () => {
      try {
        const job = await apiClient.getJobStatus(jobId);
        setActiveJob(job);

        if (job.status === 'completed' && job.artifact_id) {
          if (pollIntervalRef.current) {
            clearInterval(pollIntervalRef.current);
            pollIntervalRef.current = null;
          }
          setIsSubmitting(false);

          // Fetch full artifact and open workspace
          const artifact = await apiClient.getArtifact(job.artifact_id);
          onEssayGenerated(artifact);
        } else if (job.status === 'failed') {
          if (pollIntervalRef.current) {
            clearInterval(pollIntervalRef.current);
            pollIntervalRef.current = null;
          }
          setIsSubmitting(false);
          setFailedArtifactId(job.artifact_id || null);
          const rawErr = job.error || '';
          if (rawErr.toLowerCase().includes('timeout')) {
            setError(`Inference Timed Out: ${rawErr}`);
          } else if (rawErr.toLowerCase().includes('quality evaluation') || rawErr.toLowerCase().includes('outside acceptable target range')) {
            setError(`Quality Evaluation Rejected Draft: ${rawErr}`);
          } else if (rawErr.toLowerCase().includes('provider') || rawErr.toLowerCase().includes('502')) {
            setError(`Model Provider Failure: ${rawErr}`);
          } else {
            setError(rawErr || 'Essay generation encountered an error.');
          }
        }
      } catch (err: any) {
        // Continue polling unless network is completely down
        console.warn('Job polling error:', err);
      }
    }, 3000);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isSubmitting) return;

    const trimmedTopic = topic.trim();
    if (!trimmedTopic || trimmedTopic.length < 3) {
      setError('Please provide a valid topic of at least 3 characters.');
      return;
    }

    setError(null);
    setIsSubmitting(true);

    const brief: WritingBriefRequest = {
      topic: trimmedTopic,
      audience: audience.trim() || undefined,
      purpose: purpose.trim() || undefined,
      central_thesis: centralThesis.trim() || null,
      tone,
      target_word_count: targetWordCount,
      include_outline: true,
      additional_instructions: additionalInstructions.trim() || null,
    };

    try {
      const job = await apiClient.submitEssay(brief);
      setActiveJob(job);
      handleStartPolling(job.job_id);
    } catch (err: any) {
      setIsSubmitting(false);
      setError(err.message || 'Failed to submit essay writing brief.');
    }
  };

  const handleRetry = () => {
    setError(null);
    setFailedArtifactId(null);
    setActiveJob(null);
    setIsSubmitting(false);
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  };

  return (
    <div className="composer-container">
      <div className="composer-card">
        <div className="composer-header">
          <h1 className="composer-title">Compose Ship 30 for 30 Essay</h1>
          <p className="composer-subtitle">
            Enter a writing brief to research Lenny’s Podcast transcripts, synthesize podcast evidence,
            and draft a verified 1,250-word essay with source provenance.
          </p>
        </div>

        {error && (
          <div className="error-banner" role="alert">
            <AlertCircle size={18} />
            <div style={{ flex: 1 }}>{error}</div>
            <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
              {failedArtifactId && (
                <button
                  type="button"
                  className="btn-secondary"
                  style={{ padding: '0.25rem 0.6rem', fontSize: '0.75rem' }}
                  onClick={async () => {
                    try {
                      const art = await apiClient.getArtifact(failedArtifactId);
                      onEssayGenerated(art);
                    } catch (e) {
                      console.error(e);
                    }
                  }}
                  title="Inspect rejected draft and diagnostics in the workspace"
                >
                  <Eye size={12} />
                  <span>Inspect Draft</span>
                </button>
              )}
              <button
                type="button"
                className="btn-secondary"
                style={{ padding: '0.25rem 0.6rem', fontSize: '0.75rem' }}
                onClick={handleRetry}
              >
                <RefreshCw size={12} />
                <span>Retry</span>
              </button>
            </div>
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label" htmlFor="topic-input">
              Topic or Question <span style={{ color: 'var(--danger)' }}>*</span>
              <span className="label-hint">{topic.length}/300</span>
            </label>
            <input
              id="topic-input"
              className="form-input"
              type="text"
              placeholder="e.g. The 11-Star Product Experience and Designing Backwards"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              disabled={isSubmitting}
              maxLength={300}
              required
            />
            <p className="form-hint">The core thesis or question to ground in podcast interviews.</p>
          </div>

          <div className="form-row">
            <div className="form-group">
              <label className="form-label" htmlFor="audience-input">Target Audience</label>
              <input
                id="audience-input"
                className="form-input"
                type="text"
                value={audience}
                onChange={(e) => setAudience(e.target.value)}
                disabled={isSubmitting}
                maxLength={200}
              />
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="tone-select">Tone</label>
              <select
                id="tone-select"
                className="form-select"
                value={tone}
                onChange={(e) => setTone(e.target.value as EssayTone)}
                disabled={isSubmitting}
              >
                <option value="analytical">Analytical</option>
                <option value="conversational">Conversational</option>
                <option value="persuasive">Persuasive</option>
                <option value="educational">Educational</option>
              </select>
            </div>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="purpose-input">Purpose</label>
            <input
              id="purpose-input"
              className="form-input"
              type="text"
              value={purpose}
              onChange={(e) => setPurpose(e.target.value)}
              disabled={isSubmitting}
              maxLength={300}
            />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="thesis-input">
              Central Thesis <span className="label-hint">Optional</span>
            </label>
            <input
              id="thesis-input"
              className="form-input"
              type="text"
              placeholder="Leave blank to automatically synthesize a defensible thesis from the transcript evidence."
              value={centralThesis}
              onChange={(e) => setCentralThesis(e.target.value)}
              disabled={isSubmitting}
              maxLength={500}
            />
          </div>

          <div className="form-row">
            <div className="form-group">
              <label className="form-label" htmlFor="word-count-input">
                Target Body Word Count: {targetWordCount}
              </label>
              <input
                id="word-count-input"
                className="form-input"
                type="number"
                min={500}
                max={2500}
                step={50}
                value={targetWordCount}
                onChange={(e) => setTargetWordCount(Number(e.target.value))}
                disabled={isSubmitting}
              />
              <p className="form-hint">Standard Ship 30 for 30 essay body target is 1,250 words.</p>
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="instructions-input">
                Additional Constraints <span className="label-hint">Optional</span>
              </label>
              <textarea
                id="instructions-input"
                className="form-textarea"
                placeholder="Specific frameworks, guests, or questions to emphasize."
                value={additionalInstructions}
                onChange={(e) => setAdditionalInstructions(e.target.value)}
                disabled={isSubmitting}
                maxLength={1000}
              />
            </div>
          </div>

          <div style={{ marginTop: '1.5rem', display: 'flex', justifyContent: 'flex-end' }}>
            <button
              type="submit"
              className="btn-primary"
              disabled={isSubmitting || !topic.trim()}
              style={{ minWidth: '180px' }}
            >
              {isSubmitting ? (
                <>
                  <Loader2 size={16} className="animate-spin" />
                  <span>Researching & Drafting...</span>
                </>
              ) : (
                <>
                  <Sparkles size={16} />
                  <span>Generate Essay</span>
                </>
              )}
            </button>
          </div>
        </form>

        {activeJob && isSubmitting && (
          <div className="job-progress-card" aria-live="polite">
            <div className="job-header">
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                <Loader2 size={18} className="animate-spin" style={{ color: 'var(--primary)' }} />
                <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>Generating Essay Artifact</span>
              </div>
              <div className="job-status-pill status-running">
                <Clock size={13} />
                <span>{activeJob.elapsed_seconds.toFixed(0)}s elapsed</span>
              </div>
            </div>

            <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
              <strong>Stage:</strong> {activeJob.stage}
            </p>

            <p style={{ fontSize: '0.775rem', color: 'var(--text-muted)' }}>
              Grounding insights across 303 episodes and 17,365 chunks. Long-form generation takes approximately 60–120 seconds.
            </p>
          </div>
        )}
      </div>
    </div>
  );
};
