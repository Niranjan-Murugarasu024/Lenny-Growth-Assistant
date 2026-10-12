/**
 * Typed API client for The Lenny Growth Assistant Writing Studio.
 */
import type {
  ChatMessage,
  ChatSession,
  CreateArtifactRequest,
  EssayJobResponse,
  GenerateArtifactRequest,
  HealthReadyResponse,
  LLMSettingsResponse,
  MarkdownPreviewRequest,
  MarkdownPreviewResponse,
  ModelConfigResponse,
  ModelSwitchRequest,
  RevisionRequest,
  SaveManualVersionRequest,
  SessionListResponse,
  SessionMessagesResponse,
  TestLLMConnectionRequest,
  TestLLMConnectionResponse,
  UpdateLLMSettingsRequest,
  WritingArtifactHistoryResponse,
  WritingArtifactListResponse,
  WritingArtifactResponse,
  WritingArtifactVersionResponse,
  WritingBriefRequest,
} from './types';

export class ApiError extends Error {
  code: string;
  status: number;
  details?: any;

  constructor(message: string, code: string = 'API_ERROR', status: number = 500, details?: any) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const url = `${BASE_URL}${endpoint}`;
  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };

  let response: Response;
  try {
    response = await fetch(url, { ...options, headers });
  } catch (err: any) {
    throw new ApiError(
      `Network connection failed: ${err.message || 'Cannot reach server'}`,
      'NETWORK_ERROR',
      0
    );
  }

  if (!response.ok) {
    let errorData: any = null;
    try {
      errorData = await response.json();
    } catch {
      // Body not JSON
    }

    const errorPayload = errorData?.error || {};
    const message = errorPayload.message || errorData?.detail?.message || errorData?.detail || `HTTP Error ${response.status}: ${response.statusText}`;
    const code = errorPayload.code || errorData?.detail?.code || 'SERVER_ERROR';
    const details = errorPayload.details || errorData?.detail?.details;

    throw new ApiError(message, code, response.status, details);
  }

  return response.json();
}

export const apiClient = {
  /**
   * Submit a writing brief to generate an essay (starts async job or sync if specified).
   */
  async submitEssay(brief: WritingBriefRequest, sync: boolean = false): Promise<EssayJobResponse> {
    const query = sync ? '?sync=true' : '';
    return request<EssayJobResponse>(`/api/v1/writing/essays${query}`, {
      method: 'POST',
      body: JSON.stringify(brief),
    });
  },

  /**
   * Poll generation status of an essay job.
   */
  async getJobStatus(jobId: string): Promise<EssayJobResponse> {
    return request<EssayJobResponse>(`/api/v1/writing/jobs/${jobId}`, {
      method: 'GET',
    });
  },

  /**
   * Retrieve full artifact metadata and latest version.
   */
  async getArtifact(artifactId: string): Promise<WritingArtifactResponse> {
    return request<WritingArtifactResponse>(`/api/v1/writing/artifacts/${artifactId}`, {
      method: 'GET',
    });
  },

  /**
   * Retrieve paginated list of writing artifacts.
   */
  async listArtifacts(limit: number = 20, offset: number = 0, sessionId?: string): Promise<WritingArtifactListResponse> {
    const params = new URLSearchParams({
      limit: limit.toString(),
      offset: offset.toString(),
    });
    if (sessionId) {
      params.append('session_id', sessionId);
    }
    return request<WritingArtifactListResponse>(`/api/v1/writing/artifacts?${params.toString()}`, {
      method: 'GET',
    });
  },

  /**
   * Retrieve ordered version history summaries for an artifact.
   */
  async getArtifactVersions(artifactId: string): Promise<WritingArtifactHistoryResponse> {
    return request<WritingArtifactHistoryResponse>(`/api/v1/writing/artifacts/${artifactId}/versions`, {
      method: 'GET',
    });
  },

  /**
   * Retrieve an exact immutable snapshot of a specific artifact version.
   */
  async getSpecificVersion(artifactId: string, versionNumber: number): Promise<WritingArtifactVersionResponse> {
    return request<WritingArtifactVersionResponse>(`/api/v1/writing/artifacts/${artifactId}/versions/${versionNumber}`, {
      method: 'GET',
    });
  },

  /**
   * Save manual Markdown edits as a new immutable version.
   */
  async saveManualVersion(artifactId: string, payload: SaveManualVersionRequest): Promise<WritingArtifactResponse> {
    return request<WritingArtifactResponse>(`/api/v1/writing/artifacts/${artifactId}/versions`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  /**
   * Submit revision instructions to generate a new AI-revised immutable version.
   * If backend dispatches as durable background job, polls until completion.
   */
  async reviseArtifact(artifactId: string, payload: RevisionRequest): Promise<WritingArtifactResponse> {
    const resp = await request<WritingArtifactResponse | EssayJobResponse>(
      `/api/v1/writing/artifacts/${artifactId}/revisions`,
      {
        method: 'POST',
        body: JSON.stringify(payload),
      }
    );

    // If an asynchronous job was returned, poll until terminal state
    if ('job_id' in resp && resp.job_id) {
      const maxAttempts = 180;
      for (let i = 0; i < maxAttempts; i++) {
        await new Promise((r) => setTimeout(r, 1500));
        const status = await this.getJobStatus(resp.job_id);
        if (status.status === 'completed') {
          return await this.getArtifact(status.artifact_id || artifactId);
        }
        if (status.status === 'failed') {
          throw new ApiError(
            status.error || 'AI revision failed to complete',
            'REVISION_FAILED',
            400
          );
        }
      }
      throw new ApiError('AI revision timed out in background queue', 'TIMEOUT', 504);
    }

    return resp as WritingArtifactResponse;
  },

  /**
   * Safely render and sanitize arbitrary Markdown into HTML preview.
   */
  async previewMarkdown(markdownContent: string): Promise<MarkdownPreviewResponse> {
    const payload: MarkdownPreviewRequest = { markdown_content: markdownContent };
    return request<MarkdownPreviewResponse>('/api/v1/writing/preview', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  /**
   * Create a new persistent chat session.
   */
  async createSession(title?: string): Promise<ChatSession> {
    const body = title ? JSON.stringify({ title }) : JSON.stringify({});
    return request<ChatSession>('/api/v1/sessions', {
      method: 'POST',
      body,
    });
  },

  /**
   * List recent persistent chat sessions.
   */
  async listSessions(limit: number = 30, offset: number = 0): Promise<SessionListResponse> {
    const params = new URLSearchParams({
      limit: limit.toString(),
      offset: offset.toString(),
    });
    return request<SessionListResponse>(`/api/v1/sessions?${params.toString()}`, {
      method: 'GET',
    });
  },

  /**
   * Retrieve all chronological messages for a chat session.
   */
  async getSessionMessages(sessionId: string): Promise<SessionMessagesResponse> {
    return request<SessionMessagesResponse>(`/api/v1/sessions/${sessionId}/messages`, {
      method: 'GET',
    });
  },

  /**
   * Send a chat message to a session and get grounded answer.
   */
  async sendChatMessage(sessionId: string, message: string, orchestrator?: 'rag' | 'pi'): Promise<ChatMessage> {
    const body: Record<string, any> = { message };
    if (orchestrator) {
      body.orchestrator = orchestrator;
    }
    return request<ChatMessage>(`/api/v1/sessions/${sessionId}/messages`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },

  /**
   * Check system readiness and model inference availability.
   */
  async getHealthReady(): Promise<HealthReadyResponse> {
    return request<HealthReadyResponse>('/health/ready', {
      method: 'GET',
    });
  },

  /**
   * Directly create and persist a new Markdown or HTML artifact.
   */
  async createArtifact(payload: CreateArtifactRequest): Promise<WritingArtifactResponse> {
    return request<WritingArtifactResponse>('/api/v1/writing/artifacts', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  /**
   * Generate and persist an artifact from conversation context.
   */
  async generateArtifactFromConversation(payload: GenerateArtifactRequest): Promise<WritingArtifactResponse> {
    return request<WritingArtifactResponse>('/api/v1/writing/artifacts/generate', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  /**
   * Retrieve active model configuration and available provider options.
   */
  async getModelConfig(): Promise<ModelConfigResponse> {
    return request<ModelConfigResponse>('/api/v1/config/models', {
      method: 'GET',
    });
  },

  /**
   * Switch the active inference provider and model.
   */
  async switchModel(payload: ModelSwitchRequest): Promise<ModelConfigResponse> {
    return request<ModelConfigResponse>('/api/v1/config/models/switch', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  /**
   * Retrieve active LLM settings and provider configuration status.
   */
  async getLLMSettings(): Promise<LLMSettingsResponse> {
    return request<LLMSettingsResponse>('/api/v1/settings/llm', {
      method: 'GET',
    });
  },

  /**
   * Update active LLM provider and model setting.
   */
  async updateLLMSettings(payload: UpdateLLMSettingsRequest): Promise<LLMSettingsResponse> {
    return request<LLMSettingsResponse>('/api/v1/settings/llm', {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  },

  /**
   * Perform live connectivity test on specified provider without saving.
   */
  async testLLMConnection(payload: TestLLMConnectionRequest): Promise<TestLLMConnectionResponse> {
    return request<TestLLMConnectionResponse>('/api/v1/settings/llm/test', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
};
