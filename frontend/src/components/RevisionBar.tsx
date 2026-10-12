import React, { useState } from 'react';
import { Wand2, Loader2, Send } from 'lucide-react';
import { apiClient } from '../api/client';
import type { WritingArtifactResponse } from '../api/types';

interface RevisionBarProps {
  artifactId: string;
  onRevisionStart: () => void;
  onRevisionSuccess: (artifact: WritingArtifactResponse) => void;
  onRevisionError: (error: string) => void;
  isRevising: boolean;
}

const PRESET_INSTRUCTIONS = [
  'Make the introduction more compelling and hooks-driven',
  'Strengthen the central thesis with more guest evidence',
  'Improve narrative transitions between sections',
  'Sharpen tone to be more analytical and actionable',
  'Reduce repetition and make the conclusion more decisive',
];

export const RevisionBar: React.FC<RevisionBarProps> = ({
  artifactId,
  onRevisionStart,
  onRevisionSuccess,
  onRevisionError,
  isRevising,
}) => {
  const [instructions, setInstructions] = useState('');

  const handleSubmit = async (promptText: string) => {
    const trimmed = promptText.trim();
    if (!trimmed || isRevising) return;

    onRevisionStart();
    try {
      const updatedArtifact = await apiClient.reviseArtifact(artifactId, {
        instructions: trimmed,
      });
      setInstructions('');
      onRevisionSuccess(updatedArtifact);
    } catch (err: any) {
      onRevisionError(err.message || 'Failed to submit AI revision.');
    }
  };

  return (
    <div className="revision-bar" aria-label="AI Revision Panel">
      <div className="revision-presets">
        <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)' }}>
          Quick Refinements:
        </span>
        {PRESET_INSTRUCTIONS.map((preset, idx) => (
          <button
            key={idx}
            type="button"
            className="preset-chip"
            onClick={() => {
              setInstructions(preset);
              handleSubmit(preset);
            }}
            disabled={isRevising}
          >
            {preset}
          </button>
        ))}
      </div>

      <form
        className="revision-input-row"
        onSubmit={(e) => {
          e.preventDefault();
          handleSubmit(instructions);
        }}
      >
        <Wand2 size={16} style={{ color: 'var(--primary)' }} />
        <input
          type="text"
          className="revision-input"
          placeholder="Instruct the AI editor (e.g. 'Add a concrete takeaway table to section 2')..."
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          disabled={isRevising}
        />
        <button
          type="submit"
          className="btn-primary"
          style={{ padding: '0.5rem 0.9rem', fontSize: '0.825rem' }}
          disabled={isRevising || !instructions.trim()}
        >
          {isRevising ? (
            <>
              <Loader2 size={14} className="animate-spin" />
              <span>Revising...</span>
            </>
          ) : (
            <>
              <Send size={14} />
              <span>Revise Draft</span>
            </>
          )}
        </button>
      </form>
    </div>
  );
};
