export interface TranscriptChunkData {
  chunk_id: number;
  chunk_index: number;
  chunk_text: string;
  cosine_distance?: number | null;
  guest: string;
  title: string;
  source_path: string;
  speaker?: string | null;
  timestamp?: string | null;
  start_time_seconds?: number | null;
  alternate_sources?: string[];
}

export interface InternalSearchResponse {
  query: string;
  count: number;
  chunks: TranscriptChunkData[];
}

export interface InternalContextResponse {
  target_chunk_id: number;
  episode_id: number;
  count: number;
  chunks: TranscriptChunkData[];
}

export interface ConversationTurn {
  role: "user" | "assistant" | "system";
  content: string;
}

export interface AgentRunRequest {
  question: string;
  history?: ConversationTurn[];
  request_id?: string;
}

export interface ToolTraceEntry {
  tool_name: string;
  status: "success" | "error";
  duration_ms: number;
}

export interface AgentExecutionTrace {
  turns_count: number;
  tool_calls_count: number;
  tools_invoked: ToolTraceEntry[];
  final_text_length: number;
  sources_count: number;
  elapsed_seconds: number;
}

export interface AgentRunResponse {
  content: string;
  provider: string;
  model: string;
  sources: TranscriptChunkData[];
  retrieval_count: number;
  relevant_count: number;
  elapsed_seconds: number;
  request_id: string;
  trace?: AgentExecutionTrace;
}
