import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { EssayComposer } from '../components/EssayComposer';
import { Workspace } from '../components/Workspace';
import { SourcesDrawer } from '../components/SourcesDrawer';
import { VersionHistoryDrawer } from '../components/VersionHistoryDrawer';
import { RevisionBar } from '../components/RevisionBar';
import { apiClient } from '../api/client';
import type { WritingArtifactResponse } from '../api/types';

const mockArtifact: WritingArtifactResponse = {
  id: 'art-001',
  session_id: null,
  title: 'Designing The 11-Star Experience',
  artifact_type: 'essay',
  status: 'completed',
  created_at: '2026-10-12T00:00:00Z',
  updated_at: '2026-10-12T00:00:00Z',
  latest_version: {
    id: 'ver-001',
    artifact_id: 'art-001',
    version_number: 1,
    markdown_content: '# Designing The 11-Star Experience\n\nIntroductory paragraphs [Source 1].\n\n## References\n[Source 1] Brian Chesky',
    html_content: '<h1>Designing The 11-Star Experience</h1><p>Introductory paragraphs.</p>',
    word_count: 1250,
    writing_brief: { topic: 'Designing The 11-Star Experience' },
    sources: [
      {
        chunk_id: 101,
        guest: 'Brian Chesky',
        title: 'Design and Crisis',
        chunk_text: 'You must focus on the 11-star experience and design backwards.',
        source_url: 'https://youtube.com/watch?v=123',
        timestamp: '00:02:15',
      },
    ],
    eval_metadata: {
      word_count_check: true,
      body_word_count: 1250,
      target_word_count: 1250,
      required_sections_check: true,
      thesis_detected: true,
      sources_grounded_check: true,
      passes_all_checks: true,
    },
    model_metadata: { provider: 'ollama', model: 'qwen2.5:1.5b' },
    created_at: '2026-10-12T00:00:00Z',
  },
};

describe('EssayComposer Component', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('validates required topic before submission', async () => {
    const handleGenerated = vi.fn();
    render(<EssayComposer onEssayGenerated={handleGenerated} />);

    const submitBtn = screen.getByRole('button', { name: /Generate Essay/i });
    expect(submitBtn).toBeDisabled();

    const topicInput = screen.getByLabelText(/Topic or Question/i);
    fireEvent.change(topicInput, { target: { value: '   ' } });
    expect(submitBtn).toBeDisabled();

    fireEvent.change(topicInput, { target: { value: 'Product Market Fit' } });
    expect(submitBtn).not.toBeDisabled();
  });

  it('submits brief, displays in-flight state, and polls until completion', async () => {
    const handleGenerated = vi.fn();

    vi.spyOn(apiClient, 'submitEssay').mockResolvedValue({
      job_id: 'job_test_1',
      status: 'queued',
      stage: 'Job queued for execution',
      topic: 'Product Market Fit',
      target_word_count: 1250,
      artifact_id: null,
      version_number: null,
      error: null,
      elapsed_seconds: 0.5,
    });

    vi.spyOn(apiClient, 'getJobStatus').mockResolvedValue({
      job_id: 'job_test_1',
      status: 'completed',
      stage: 'Completed generation',
      topic: 'Product Market Fit',
      target_word_count: 1250,
      artifact_id: 'art-001',
      version_number: 1,
      error: null,
      elapsed_seconds: 12.0,
    });

    vi.spyOn(apiClient, 'getArtifact').mockResolvedValue(mockArtifact);

    render(<EssayComposer onEssayGenerated={handleGenerated} />);

    const topicInput = screen.getByLabelText(/Topic or Question/i);
    fireEvent.change(topicInput, { target: { value: 'Product Market Fit' } });

    const submitBtn = screen.getByRole('button', { name: /Generate Essay/i });
    fireEvent.click(submitBtn);

    // Prevents duplicate clicks while in-flight
    expect(submitBtn).toBeDisabled();
    expect(screen.getByText(/Researching & Drafting/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(apiClient.submitEssay).toHaveBeenCalledWith(
        expect.objectContaining({ topic: 'Product Market Fit' })
      );
    });
  });

  it('handles job failure and provides retry action', async () => {
    vi.spyOn(apiClient, 'submitEssay').mockRejectedValue(new Error('LLM model unavailable'));

    render(<EssayComposer onEssayGenerated={vi.fn()} />);

    const topicInput = screen.getByLabelText(/Topic or Question/i);
    fireEvent.change(topicInput, { target: { value: 'Failing Topic' } });

    fireEvent.click(screen.getByRole('button', { name: /Generate Essay/i }));

    await waitFor(() => {
      expect(screen.getByText(/LLM model unavailable/i)).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Retry/i })).toBeInTheDocument();
    });
  });
});

describe('Workspace Component', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders title, live word count, and initial saved status', () => {
    render(<Workspace artifact={mockArtifact} onArtifactUpdated={vi.fn()} />);

    expect(screen.getByText('Designing The 11-Star Experience')).toBeInTheDocument();
    expect(screen.getByText('v1')).toBeInTheDocument();
    expect(screen.getByText('Saved')).toBeInTheDocument();
    expect(screen.getByText('1250')).toBeInTheDocument();
  });

  it('updates dirty state when markdown is edited and allows discarding', () => {
    render(<Workspace artifact={mockArtifact} onArtifactUpdated={vi.fn()} />);

    const textarea = screen.getByLabelText('Markdown Essay Editor');
    fireEvent.change(textarea, { target: { value: '# Edited Title\n\nNew draft content' } });

    expect(screen.getByText('● Unsaved edits')).toBeInTheDocument();
    const discardBtn = screen.getByRole('button', { name: /Discard/i });
    expect(discardBtn).toBeInTheDocument();

    // Mock confirm dialog
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    fireEvent.click(discardBtn);

    expect(screen.getByText('Saved')).toBeInTheDocument();
  });

  it('saves manual edits as a new immutable version v2', async () => {
    const updatedArtifact: WritingArtifactResponse = {
      ...mockArtifact,
      latest_version: {
        ...mockArtifact.latest_version,
        version_number: 2,
        markdown_content: '# Updated Title\n\nSaved content',
        word_count: 1280,
      },
    };

    vi.spyOn(apiClient, 'saveManualVersion').mockResolvedValue(updatedArtifact);
    vi.spyOn(apiClient, 'getArtifactVersions').mockResolvedValue({
      artifact_id: 'art-001',
      title: 'Designing The 11-Star Experience',
      versions: [
        { id: 'v1', version_number: 1, word_count: 1250, created_at: '2026-10-12T00:00:00Z' },
        { id: 'v2', version_number: 2, word_count: 1280, created_at: '2026-10-12T00:05:00Z' },
      ],
    });

    const handleUpdated = vi.fn();
    render(<Workspace artifact={mockArtifact} onArtifactUpdated={handleUpdated} />);

    const textarea = screen.getByLabelText('Markdown Essay Editor');
    fireEvent.change(textarea, { target: { value: '# Updated Title\n\nSaved content' } });

    const saveBtn = screen.getByRole('button', { name: /Save New Version/i });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(apiClient.saveManualVersion).toHaveBeenCalledWith(
        'art-001',
        expect.objectContaining({ markdown_content: '# Updated Title\n\nSaved content' })
      );
      expect(handleUpdated).toHaveBeenCalledWith(updatedArtifact);
    });
  });
});

describe('SourcesDrawer & VersionHistoryDrawer', () => {
  it('SourcesDrawer displays guest, title, chunk text, and source link', () => {
    render(
      <SourcesDrawer
        isOpen={true}
        onClose={vi.fn()}
        sources={mockArtifact.latest_version.sources}
        versionNumber={1}
      />
    );

    expect(screen.getByText('Brian Chesky')).toBeInTheDocument();
    expect(screen.getByText('Design and Crisis')).toBeInTheDocument();
    expect(screen.getByText(/11-star experience and design backwards/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Listen \/ View/i })).toHaveAttribute('href', 'https://youtube.com/watch?v=123');
  });

  it('VersionHistoryDrawer displays quality evaluation checks', () => {
    render(
      <VersionHistoryDrawer
        isOpen={true}
        onClose={vi.fn()}
        versions={[{ id: 'v1', version_number: 1, word_count: 1250, created_at: '2026-10-12T00:00:00Z' }]}
        currentVersionNumber={1}
        evalMetadata={mockArtifact.latest_version.eval_metadata}
        onSelectVersion={vi.fn()}
      />
    );

    expect(screen.getByText(/Deterministic Quality Checks/i)).toBeInTheDocument();
    expect(screen.getByText(/Defensible Thesis Statement Identified/i)).toBeInTheDocument();
    expect(screen.getByText(/Citations Grounded In PostgreSQL Corpus/i)).toBeInTheDocument();
  });
});

describe('RevisionBar Component', () => {
  it('submits revision prompt when preset chip is clicked', async () => {
    vi.spyOn(apiClient, 'reviseArtifact').mockResolvedValue(mockArtifact);

    const onStart = vi.fn();
    const onSuccess = vi.fn();

    render(
      <RevisionBar
        artifactId="art-001"
        isRevising={false}
        onRevisionStart={onStart}
        onRevisionSuccess={onSuccess}
        onRevisionError={vi.fn()}
      />
    );

    const presetChip = screen.getByRole('button', { name: /Strengthen the central thesis/i });
    fireEvent.click(presetChip);

    expect(onStart).toHaveBeenCalled();
    await waitFor(() => {
      expect(apiClient.reviseArtifact).toHaveBeenCalledWith('art-001', {
        instructions: expect.stringContaining('Strengthen the central thesis'),
      });
      expect(onSuccess).toHaveBeenCalledWith(mockArtifact);
    });
  });
});
