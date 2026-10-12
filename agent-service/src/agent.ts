import {
  createAgentSession,
  DefaultResourceLoader,
  getAgentDir,
  SessionManager,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";
import { config } from "./config.js";
import { createGetTranscriptContextTool } from "./tools/get-transcript-context.js";
import { createSearchTranscriptsTool } from "./tools/search-transcripts.js";
import {
  AgentExecutionTrace,
  AgentRunRequest,
  AgentRunResponse,
  ToolTraceEntry,
  TranscriptChunkData,
} from "./types.js";

const REQUIRED_TOOLS = ["search_transcripts", "get_transcript_context"] as const;
const RUN_TIMEOUT_MS = 360_000;

const SYSTEM_PROMPT = `You are Lenny's Growth Assistant, a specialized AI assistant grounded strictly in Lenny's Podcast transcripts.

OPERATIONAL INSTRUCTIONS:
1. Call 'search_transcripts' exactly once to find transcript evidence for the question. Never call 'search_transcripts' more than once.
2. If surrounding lines are essential, you may call 'get_transcript_context' once; otherwise proceed immediately to formulating your answer.
3. Ground your answer strictly in the retrieved transcript passages. Do not invent facts, guests, or quotes.
4. If no relevant transcript evidence is found, politely abstain stating the archives lack evidence.
5. Always cite your sources in your answer using markers like [Source 1], [Source 2] with guest and episode name.
6. Keep your answer direct, structured, and concise (2-3 paragraphs).`;

/**
 * Diagnostic helper to verify that runtime tool registration satisfies
 * strict security boundaries (only required custom tools active, no built-ins,
 * no ambient extensions).
 */
export async function verifyToolConfiguration(): Promise<{
  activeTools: string[];
  allTools: string[];
  valid: boolean;
  reason?: string;
}> {
  const dummySources: TranscriptChunkData[] = [];
  const searchTool = createSearchTranscriptsTool(dummySources, config.backendUrl, config.agentInternalToken);
  const contextTool = createGetTranscriptContextTool(dummySources, config.backendUrl, config.agentInternalToken);

  const cwd = process.cwd();
  const agentDir = getAgentDir();
  const settingsManager = SettingsManager.create(cwd, agentDir);

  const resourceLoader = new DefaultResourceLoader({
    cwd,
    agentDir,
    settingsManager,
    systemPromptOverride: () => SYSTEM_PROMPT,
    appendSystemPromptOverride: () => [],
    noExtensions: true,
    noSkills: true,
    noPromptTemplates: true,
    noThemes: true,
    noContextFiles: true,
  });
  await resourceLoader.reload();

  const { session } = await createAgentSession({
    resourceLoader,
    settingsManager,
    sessionManager: SessionManager.inMemory(),
    noTools: "builtin",
    tools: [...REQUIRED_TOOLS],
    customTools: [searchTool, contextTool],
  });

  const activeTools = session.getActiveToolNames();
  const allTools = session.getAllTools().map((t) => t.name);
  await session.dispose();

  // Validate active tools
  for (const req of REQUIRED_TOOLS) {
    if (!activeTools.includes(req)) {
      return {
        activeTools,
        allTools,
        valid: false,
        reason: `Required tool '${req}' is not active.`,
      };
    }
  }

  // Validate forbidden tools
  const forbidden = ["bash", "powershell", "read", "write", "edit", "grep", "find", "ls"];
  for (const f of forbidden) {
    if (activeTools.includes(f) || allTools.includes(f)) {
      return {
        activeTools,
        allTools,
        valid: false,
        reason: `Forbidden built-in tool '${f}' was exposed.`,
      };
    }
  }

  return { activeTools, allTools, valid: true };
}

export async function runAgent(
  request: AgentRunRequest,
): Promise<AgentRunResponse> {
  const startTime = Date.now();
  const requestId =
    request.request_id || `req_agent_${Math.random().toString(36).substring(2, 10)}`;

  const collectedSources: TranscriptChunkData[] = [];
  const toolTraces: ToolTraceEntry[] = [];
  let turnsCount = 0;
  const toolStartTimes = new Map<string, number>();

  // 1. Initialize strictly controlled custom tools
  const searchTool = createSearchTranscriptsTool(
    collectedSources,
    config.backendUrl,
    config.agentInternalToken,
  );
  const contextTool = createGetTranscriptContextTool(
    collectedSources,
    config.backendUrl,
    config.agentInternalToken,
  );

  // 2. Configure model runtime credentials
  const providerKey =
    config.modelProvider === "ollama" ? "openai" : config.modelProvider;
  const apiKey =
    config.modelApiKey || (config.modelProvider === "ollama" ? "ollama-local" : "");

  if (providerKey === "openai" && !process.env.OPENAI_API_KEY) {
    process.env.OPENAI_API_KEY = apiKey;
  }

  // 3. Define model specification
  const modelSpec = {
    type: "chat" as const,
    id: config.modelId,
    name: `${config.modelProvider}: ${config.modelId}`,
    api: "openai-completions" as const,
    baseUrl: config.modelBaseUrl,
    provider: providerKey,
    contextWindow: 16384,
    maxTokens: 512,
    reasoning: false,
    input: ["text" as const],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
  };

  // 4. Create explicit isolated resource loader without ambient extensions
  const cwd = process.cwd();
  const agentDir = getAgentDir();
  const settingsManager = SettingsManager.create(cwd, agentDir);

  const resourceLoader = new DefaultResourceLoader({
    cwd,
    agentDir,
    settingsManager,
    systemPromptOverride: () => SYSTEM_PROMPT,
    appendSystemPromptOverride: () => [],
    noExtensions: true,
    noSkills: true,
    noPromptTemplates: true,
    noThemes: true,
    noContextFiles: true,
  });
  await resourceLoader.reload();

  // 5. Create isolated session with zero built-in tools
  const { session } = await createAgentSession({
    model: modelSpec,
    resourceLoader,
    settingsManager,
    sessionManager: SessionManager.inMemory(),
    thinkingLevel: "off",
    noTools: "builtin",
    tools: [...REQUIRED_TOOLS],
    customTools: [searchTool, contextTool],
  });

  // Verify tool registration invariant
  const activeTools = session.getActiveToolNames();
  for (const req of REQUIRED_TOOLS) {
    if (!activeTools.includes(req)) {
      await session.dispose();
      throw new Error(`Security violation: Required tool '${req}' was not registered.`);
    }
  }

  // Set runtime API key if needed
  if (session.modelRuntime && apiKey) {
    try {
      session.modelRuntime.setRuntimeApiKey(providerKey, apiKey);
    } catch {
      // Ignore if not supported
    }
  }

  // 6. Subscribe to observable SDK events for sanitized execution tracing
  session.subscribe((event: any) => {
    if (event.type === "agent_start") {
      console.log(`[PiAgent:${requestId}] Agent execution started.`);
    } else if (event.type === "turn_start") {
      turnsCount++;
      console.log(`[PiAgent:${requestId}] Model turn ${turnsCount} started.`);
    } else if (event.type === "turn_end") {
      console.log(`[PiAgent:${requestId}] Model turn ${turnsCount} ended.`);
    } else if (event.type === "tool_execution_start") {
      const callId = event.toolCallId || event.toolName;
      toolStartTimes.set(callId, Date.now());
      console.log(`[PiAgent:${requestId}] Tool '${event.toolName}' started.`);
    } else if (event.type === "tool_execution_end") {
      const callId = event.toolCallId || event.toolName;
      const started = toolStartTimes.get(callId) || Date.now();
      const dur = Date.now() - started;
      const status: "success" | "error" = event.isError ? "error" : "success";
      toolTraces.push({
        tool_name: event.toolName,
        status,
        duration_ms: dur,
      });
      console.log(
        `[PiAgent:${requestId}] Tool '${event.toolName}' finished in ${dur}ms (status: ${status}).`,
      );
    } else if (event.type === "agent_end") {
      console.log(`[PiAgent:${requestId}] Agent execution finished.`);
    }
  });

  // 7. Construct user prompt including bounded history
  let promptText = "";
  if (request.history && request.history.length > 0) {
    const historySnippet = request.history
      .map((turn) => `${turn.role.toUpperCase()}: ${turn.content}`)
      .join("\n\n");
    promptText = `[CONVERSATION HISTORY]\n${historySnippet}\n\n[USER QUESTION]\n${request.question}`;
  } else {
    promptText = request.question;
  }

  let isTimedOut = false;
  const timeoutTimer = setTimeout(() => {
    isTimedOut = true;
    console.warn(`[PiAgent:${requestId}] Run timed out after ${RUN_TIMEOUT_MS}ms, aborting.`);
    session.abort().catch(() => {});
  }, RUN_TIMEOUT_MS);

  try {
    // 8. Execute autonomous agent session
    await session.prompt(promptText);

    if (isTimedOut) {
      throw new Error(`Agent execution exceeded bounded timeout of ${RUN_TIMEOUT_MS / 1000}s.`);
    }

    // 9. Extract clean assistant answer (ignoring thinking parts)
    const messages = session.messages || [];
    const assistantMessages = messages.filter((m) => m.role === "assistant");
    const lastAssistantMsg = assistantMessages[assistantMessages.length - 1];

    let rawContent = "";
    if (lastAssistantMsg) {
      if (typeof lastAssistantMsg.content === "string") {
        rawContent = lastAssistantMsg.content;
      } else if (Array.isArray(lastAssistantMsg.content)) {
        rawContent = lastAssistantMsg.content
          .filter((part: any) => part.type === "text" || (!part.type && part.text))
          .map((part: any) => part.text || "")
          .join("")
          .trim();
      }
    }

    if (!rawContent) {
      rawContent =
        "I apologize, but I could not find relevant discussions in Lenny's Podcast transcripts to answer your question.";
    }

    const elapsedSeconds = Number(((Date.now() - startTime) / 1000).toFixed(2));
    const trace: AgentExecutionTrace = {
      turns_count: turnsCount,
      tool_calls_count: toolTraces.length,
      tools_invoked: toolTraces,
      final_text_length: rawContent.length,
      sources_count: collectedSources.length,
      elapsed_seconds: elapsedSeconds,
    };

    console.log(
      `[PiAgent:${requestId}] Completed successfully in ${elapsedSeconds}s (turns: ${turnsCount}, tools: ${toolTraces.length}, sources: ${collectedSources.length}).`,
    );

    return {
      content: rawContent,
      provider: `pi-agent-${config.modelProvider}`,
      model: config.modelId,
      sources: collectedSources,
      retrieval_count: collectedSources.length,
      relevant_count: collectedSources.length,
      elapsed_seconds: elapsedSeconds,
      request_id: requestId,
      trace,
    };
  } finally {
    clearTimeout(timeoutTimer);
    try {
      await session.dispose();
    } catch {
      // Ignore cleanup error
    }
  }
}
