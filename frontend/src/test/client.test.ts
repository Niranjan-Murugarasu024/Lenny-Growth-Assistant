import { describe, it, expect, vi, beforeEach } from 'vitest';
import { apiClient } from '../api/client';
import type { WritingBriefRequest } from '../api/types';

describe('apiClient', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('submits essay brief to POST /api/v1/writing/essays', async () => {
    const mockResponse = {
      job_id: 'job_123',
      status: 'queued',
      stage: 'Job queued',
      topic: 'Test Topic',
      target_word_count: 1250,
      elapsed_seconds: 0.1,
    };

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockResponse,
    });

    const brief: WritingBriefRequest = {
      topic: 'Test Topic',
      target_word_count: 1250,
      tone: 'analytical',
    };

    const res = await apiClient.submitEssay(brief);
    expect(res.job_id).toBe('job_123');
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/v1/writing/essays',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
      })
    );
  });

  it('polls job status with GET /api/v1/writing/jobs/{job_id}', async () => {
    const mockJob = {
      job_id: 'job_456',
      status: 'running',
      stage: 'Drafting essay',
      topic: 'Retention loops',
      target_word_count: 1250,
      elapsed_seconds: 15.4,
    };

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockJob,
    });

    const res = await apiClient.getJobStatus('job_456');
    expect(res.status).toBe('running');
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/v1/writing/jobs/job_456',
      expect.objectContaining({ method: 'GET' })
    );
  });

  it('throws ApiError with backend error message and code on HTTP 4xx/5xx', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      json: async () => ({
        error: {
          code: 'ARTIFACT_NOT_FOUND',
          message: "Artifact 'abc-123' does not exist.",
        },
      }),
    });

    await expect(apiClient.getArtifact('abc-123')).rejects.toThrow("Artifact 'abc-123' does not exist.");
  });

  it('safely renders preview via POST /api/v1/writing/preview', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        html_content: '<h1>Preview Title</h1>',
        word_count: 150,
      }),
    });

    const res = await apiClient.previewMarkdown('# Preview Title\n\nContent');
    expect(res.html_content).toBe('<h1>Preview Title</h1>');
    expect(res.word_count).toBe(150);
  });
});
