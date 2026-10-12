import React from 'react';
import { X, History, CheckCircle2, XCircle, FileText, ChevronRight } from 'lucide-react';
import type { EvaluationMetadata, WritingArtifactVersionSummary } from '../api/types';

interface VersionHistoryDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  versions: WritingArtifactVersionSummary[];
  currentVersionNumber: number;
  evalMetadata: EvaluationMetadata;
  onSelectVersion: (versionNumber: number) => void;
}

export const VersionHistoryDrawer: React.FC<VersionHistoryDrawerProps> = ({
  isOpen,
  onClose,
  versions,
  currentVersionNumber,
  evalMetadata,
  onSelectVersion,
}) => {
  if (!isOpen) return null;

  return (
    <div className="drawer-backdrop" onClick={onClose} role="dialog" aria-modal="true">
      <div className="drawer-panel" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <History size={18} style={{ color: 'var(--primary)' }} />
            <h2 className="drawer-title">Version History & Evaluation</h2>
          </div>
          <button
            type="button"
            className="btn-secondary"
            style={{ padding: '0.35rem 0.5rem', borderRadius: '50%' }}
            onClick={onClose}
            aria-label="Close version history drawer"
          >
            <X size={16} />
          </button>
        </div>

        <div className="drawer-content">
          {/* Active Version Evaluation Card */}
          <div className="eval-card">
            {(() => {
              const isWordCountPass = Boolean(evalMetadata.word_count_in_range ?? evalMetadata.word_count_check ?? false);
              const isSectionsPass = Boolean(evalMetadata.required_sections_check ?? (evalMetadata.has_title && (evalMetadata.headings_count ?? 0) >= 2) ?? false);
              const isThesisPass = Boolean(evalMetadata.thesis_detected ?? false);
              const isCitationsPass = Boolean(evalMetadata.all_citations_verified ?? evalMetadata.sources_grounded_check ?? false);
              const issuesList: string[] = (evalMetadata.feedback || evalMetadata.failure_reasons || []) as string[];
              const targetWc = Number(evalMetadata.target_word_count || 1250);
              const lowerRange = Math.round(targetWc * 0.9);
              const upperRange = Math.round(targetWc * 1.1);

              return (
                <>
                  <h3 style={{ fontSize: '0.9rem', fontWeight: 700, marginBottom: '0.6rem', color: 'var(--text-main)' }}>
                    Deterministic Quality Checks (v{currentVersionNumber})
                  </h3>

                  <div className={`eval-item ${isWordCountPass ? 'pass' : 'fail'}`}>
                    {isWordCountPass ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
                    <span>
                      Body Word Count: {evalMetadata.body_word_count ?? 'N/A'} words (Range: {lowerRange}–{upperRange}, Target: {targetWc})
                    </span>
                  </div>

                  <div className={`eval-item ${isSectionsPass ? 'pass' : 'fail'}`}>
                    {isSectionsPass ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
                    <span>Required Sections (Title, Intro, Subsections, Conclusion, References)</span>
                  </div>

                  <div className={`eval-item ${isThesisPass ? 'pass' : 'fail'}`}>
                    {isThesisPass ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
                    <span>Defensible Thesis Statement Identified</span>
                  </div>

                  <div className={`eval-item ${isCitationsPass ? 'pass' : 'fail'}`}>
                    {isCitationsPass ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
                    <span>Citations Grounded In PostgreSQL Corpus</span>
                  </div>

                  {issuesList.length > 0 && (
                    <div style={{ marginTop: '0.6rem', padding: '0.5rem', background: 'var(--danger-light)', borderRadius: '4px', fontSize: '0.75rem', color: 'var(--danger)' }}>
                      <strong>Issues Detected:</strong>
                      <ul style={{ paddingLeft: '1rem', marginTop: '0.25rem' }}>
                        {issuesList.map((r, i) => (
                          <li key={i}>{r}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </>
              );
            })()}

            <p style={{ fontSize: '0.725rem', color: 'var(--text-muted)', marginTop: '0.6rem' }}>
              * Structural verification confirms length and citation provenance, not overall subjective writing style.
            </p>
          </div>

          <h3 style={{ fontSize: '0.9rem', fontWeight: 700, color: 'var(--text-main)', marginTop: '0.5rem' }}>
            Saved Snapshots ({versions.length})
          </h3>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            {[...versions].reverse().map((v) => {
              const isCurrent = v.version_number === currentVersionNumber;
              const formattedDate = new Date(v.created_at).toLocaleString();

              return (
                <div
                  key={v.id}
                  onClick={() => onSelectVersion(v.version_number)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '0.75rem 1rem',
                    background: isCurrent ? 'var(--primary-light)' : 'var(--bg-subtle)',
                    border: isCurrent ? '1px solid var(--primary-border)' : '1px solid var(--border-light)',
                    borderRadius: 'var(--radius-md)',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                    <FileText size={18} style={{ color: isCurrent ? 'var(--primary)' : 'var(--text-muted)' }} />
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                        <span style={{ fontWeight: 700, fontSize: '0.9rem', color: isCurrent ? 'var(--primary)' : 'var(--text-main)' }}>
                          Version {v.version_number}
                        </span>
                        {isCurrent && (
                          <span className="version-chip" style={{ fontSize: '0.675rem', background: '#ffffff' }}>
                            Current
                          </span>
                        )}
                      </div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.1rem' }}>
                        {v.word_count} words • {formattedDate}
                      </div>
                    </div>
                  </div>

                  <ChevronRight size={16} style={{ color: 'var(--text-faint)' }} />
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};
