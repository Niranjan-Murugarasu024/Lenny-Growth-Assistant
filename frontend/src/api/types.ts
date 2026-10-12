/**
 * TypeScript types matching backend API schemas for The Lenny Growth Assistant Writing Studio.
 */

export type EssayTone = 'conversational' | 'analytical' | 'persuasive' | 'educational';

export interface WritingBriefRequest {
  topic: string;
  audience?: string;
  purpose?: string;
  central_thesis?: string | null;
  tone?: EssayTone;
  target_word_count?: number;
  include_outline?: boolean;
  session_id?: string | null;
  additional_instructions?: string | null;
}

export interface EssayJobResponse {
  job_id: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | string;
  stage: string;
  topic: string;
  target_word_count: number;
  artifact_id: string | null;
  version_number: number | null;
  error: string | null;
  elapsed_seconds: number;
}

export interface WritingArtifactVersionSummary {
  id: string;
  version_number: number;
  word_count: number;
  created_at: string;
}

export interface SourceMetadata {
  chunk_id?: number;
  chunk_index?: number;
  chunk_text?: string;
  guest?: string;
  title?: string;
  speaker?: string;
  source_path?: string;
  source_url?: string;
  start_time_seconds?: number;
  timestamp?: string;
  cosine_distance?: number;
  embedding_model?: string;
  [key: string]: any;
}

export interface EvaluationMetadata {
  body_word_count?: number;
  target_word_count?: number;
  word_count_check?: boolean;
  required_sections_check?: boolean;
  sections_present?: string[];
  thesis_detected?: boolean;
  thesis_statement?: string;
  sources_grounded_check?: boolean;
  referenced_source_markers?: string[];
  missing_sources?: string[];
  invalid_sources?: string[];
  repetition_check?: boolean;
  passes_all_checks?: boolean;
  failure_reasons?: string[];
  [key: string]: any;
}

export interface WritingArtifactVersionResponse {
  id: string;
  artifact_id: string;
  version_number: number;
  markdown_content: string;
  html_content: string;
  word_count: number;
  writing_brief: Record<string, any>;
  sources: SourceMetadata[];
  eval_metadata: EvaluationMetadata;
  model_metadata: Record<string, any>;
  created_at: string;
}

export interface WritingArtifactResponse {
  id: string;
  session_id: string | null;
  title: string;
  artifact_type: string;
  status: string;
  latest_version: WritingArtifactVersionResponse;
  created_at: string;
  updated_at: string;
}

export interface WritingArtifactHistoryResponse {
  artifact_id: string;
  title: string;
  versions: WritingArtifactVersionSummary[];
}

export interface WritingArtifactListItem {
  id: string;
  session_id: string | null;
  title: string;
  artifact_type: string;
  status: string;
  latest_version_number: number;
  latest_word_count: number;
  created_at: string;
  updated_at: string;
}

export interface WritingArtifactListResponse {
  artifacts: WritingArtifactListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface RevisionRequest {
  instructions: string;
  target_word_count?: number | null;
}

export interface SaveManualVersionRequest {
  markdown_content: string;
  note?: string | null;
}

export interface MarkdownPreviewRequest {
  markdown_content: string;
}

export interface MarkdownPreviewResponse {
  html_content: string;
  word_count: number;
}

export interface ApiErrorPayload {
  code: string;
  message: string;
  details?: any;
}

export interface ChatSession {
  id: string;
  title: string | null;
  user_metadata?: Record<string, any> | null;
  created_at: string;
  updated_at: string;
}

export interface SessionListResponse {
  sessions: ChatSession[];
  total: number;
}

export interface SourceReference {
  citation_index: number;
  is_cited: boolean;
  chunk_id: number;
  chunk_index: number;
  source_path: string;
  guest: string;
  title: string;
  speaker?: string | null;
  timestamp?: string | null;
  start_time_seconds?: number | null;
  cosine_distance: number;
  excerpt: string;
  alternate_sources?: string[];
  source_url?: string | null;
  youtube_video_id?: string | null;
  youtube_url?: string | null;
}

export interface ChatMessage {
  id: number;
  session_id: string;
  role: 'user' | 'assistant';
  content: string;
  provider?: string | null;
  model?: string | null;
  sources?: SourceReference[] | null;
  request_id?: string | null;
  created_at: string;
}

export interface SessionMessagesResponse {
  session_id: string;
  messages: ChatMessage[];
}

export interface HealthReadyResponse {
  status: string;
  database: Record<string, any>;
  inference: Record<string, any>;
  redis?: Record<string, any> | null;
  queue?: Record<string, any> | null;
}

export interface CreateArtifactRequest {
  title: string;
  content: string;
  artifact_type?: 'document' | 'html' | 'essay';
  session_id?: string | null;
  sources?: SourceMetadata[];
  writing_brief?: Record<string, any>;
}

export interface GenerateArtifactRequest {
  session_id: string;
  prompt: string;
  artifact_type?: 'document' | 'html';
  title?: string;
}

export interface ModelOptionInfo {
  id: string;
  provider: string;
  model: string;
  label: string;
  purpose: string;
  status: 'available' | 'unconfigured' | 'unavailable' | string;
  status_message?: string | null;
  is_active: boolean;
}

export interface ModelConfigResponse {
  active_provider: string;
  active_model: string;
  displayed_label: string;
  fallback_enabled: boolean;
  models: ModelOptionInfo[];
}

export interface ModelSwitchRequest {
  provider: 'ollama' | 'litellm' | 'nvidia';
  model?: string;
}

export interface LLMProviderInfo {
  id: string; // 'ollama' | 'nvidia'
  name: string; // 'Ollama' | 'NVIDIA NIM'
  model: string; // 'qwen2.5:1.5b' | 'openai/gpt-oss-20b'
  category: 'local' | 'cloud' | string;
  configured: boolean;
  status: 'not_configured' | 'configured' | 'connected' | 'unavailable' | 'unknown' | string;
  status_message?: string | null;
  is_active: boolean;
}

export interface LLMSettingsResponse {
  active_provider: string;
  active_model: string;
  active_category: string;
  fallback_enabled: boolean;
  providers: LLMProviderInfo[];
}

export interface UpdateLLMSettingsRequest {
  provider: string;
  model?: string;
}

export interface TestLLMConnectionRequest {
  provider: string;
}

export interface TestLLMConnectionResponse {
  provider: string;
  model: string;
  connected: boolean;
  status: string;
  elapsed_seconds: number;
  message: string;
}


