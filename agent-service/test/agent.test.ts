import { describe, it, expect, vi, beforeEach } from "vitest";
import { createApp } from "../src/server.js";
import { createSearchTranscriptsTool } from "../src/tools/search-transcripts.js";
import { createGetTranscriptContextTool } from "../src/tools/get-transcript-context.js";
import { TranscriptChunkData } from "../src/types.js";
import { verifyToolConfiguration } from "../src/agent.js";

describe("Agent Service Probes & Tools", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("GET /health/live returns ok status", async () => {
    const app = createApp();
    const server = app.listen(0);
    const port = (server.address() as any).port;

    try {
      const res = await fetch(`http://127.0.0.1:${port}/health/live`);
      expect(res.status).toBe(200);
      const data = await res.json();
      expect(data.status).toBe("ok");
      expect(data.service).toBe("lenny-pi-agent");
    } finally {
      server.close();
    }
  });

  it("GET /health/ready reports verified tool status and connected backend", async () => {
    const originalFetch = globalThis.fetch;
    const mockFetch = vi.fn().mockImplementation((url: string, opts?: any) => {
      if (url.includes("/health/live")) {
        return Promise.resolve({ ok: true, status: 200 } as any);
      }
      return originalFetch(url, opts);
    });
    vi.stubGlobal("fetch", mockFetch);

    const app = createApp();
    const server = app.listen(0);
    const port = (server.address() as any).port;

    try {
      const res = await originalFetch(`http://127.0.0.1:${port}/health/ready`);
      expect(res.status).toBe(200);
      const data = await res.json();
      expect(data.status).toBe("ready");
      expect(data.tools.status).toBe("verified");
      expect(data.tools.active).toEqual(["search_transcripts", "get_transcript_context"]);
      expect(data.tools.builtins_disabled).toBe(true);
    } finally {
      server.close();
      vi.stubGlobal("fetch", originalFetch);
    }
  });

  it("POST /v1/agent/run rejects empty question with 400", async () => {
    const app = createApp();
    const server = app.listen(0);
    const port = (server.address() as any).port;

    try {
      const res = await fetch(`http://127.0.0.1:${port}/v1/agent/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: "   " }),
      });
      expect(res.status).toBe(400);
      const data = await res.json();
      expect(data.error.code).toBe("INVALID_REQUEST");
    } finally {
      server.close();
    }
  });

  it("verifyToolConfiguration enforces strictly custom tools and rejects built-ins", async () => {
    const check = await verifyToolConfiguration();
    expect(check.valid).toBe(true);
    expect(check.activeTools).toContain("search_transcripts");
    expect(check.activeTools).toContain("get_transcript_context");

    const forbidden = ["bash", "powershell", "read", "write", "edit", "grep", "find", "ls"];
    for (const f of forbidden) {
      expect(check.activeTools).not.toContain(f);
      expect(check.allTools).not.toContain(f);
    }
  });

  it("search_transcripts tool retrieves and collects chunks correctly", async () => {
    const collected: TranscriptChunkData[] = [];
    const mockChunks: TranscriptChunkData[] = [
      {
        chunk_id: 42,
        chunk_index: 2,
        chunk_text: "Retention is the single most important metric.",
        cosine_distance: 0.18,
        guest: "Casey Winters",
        title: "Scaling Growth",
        source_path: "episodes/casey-winters/transcript.md",
        speaker: "Casey",
        timestamp: "00:05:30",
        start_time_seconds: 330,
      },
    ];

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        query: "retention",
        count: 1,
        chunks: mockChunks,
      }),
    });
    vi.stubGlobal("fetch", mockFetch);

    const tool = createSearchTranscriptsTool(collected, "http://mock-backend:8000", "test-token");
    const result = await tool.execute(
      "call-1",
      { query: "retention", top_k: 3, max_distance: 0.25 },
    );

    expect(mockFetch).toHaveBeenCalledWith(
      "http://mock-backend:8000/internal/v1/transcripts/search",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "X-Internal-Token": "test-token" }),
      }),
    );
    expect(collected.length).toBe(1);
    expect(collected[0].chunk_id).toBe(42);
    expect(result.content[0].text).toContain("Casey Winters");
    expect(result.content[0].text).toContain("Retention is the single most important metric.");
  });

  it("search_transcripts distinguishes empty results from backend errors", async () => {
    const collected: TranscriptChunkData[] = [];

    // Case 1: Empty search results (valid retrieval with no matches)
    const mockFetchEmpty = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ query: "obscure-topic", count: 0, chunks: [] }),
    });
    vi.stubGlobal("fetch", mockFetchEmpty);

    const tool = createSearchTranscriptsTool(collected, "http://mock-backend:8000", "test-token");
    const emptyResult = await tool.execute("call-empty", { query: "obscure-topic" });
    expect(emptyResult.content[0].text).toContain("No transcript passages found");
    expect(emptyResult.details.count).toBe(0);

    // Case 2: Backend error (HTTP 500)
    const mockFetchError = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: async () => "Internal server error occurred",
    });
    vi.stubGlobal("fetch", mockFetchError);

    const errorResult = await tool.execute("call-err", { query: "fail-query" });
    expect(errorResult.content[0].text).toContain("Search failed with status 500");
    expect(errorResult.details.status).toBe(500);
  });

  it("get_transcript_context tool retrieves chronological context", async () => {
    const collected: TranscriptChunkData[] = [];
    const mockContextChunks: TranscriptChunkData[] = [
      {
        chunk_id: 10,
        chunk_index: 0,
        chunk_text: "Let us start the interview.",
        guest: "Elena Verna",
        title: "B2B Growth",
        source_path: "episodes/elena-verna/transcript.md",
        speaker: "Lenny",
        timestamp: "00:00:10",
      },
      {
        chunk_id: 11,
        chunk_index: 1,
        chunk_text: "PLG requires product market fit first.",
        guest: "Elena Verna",
        title: "B2B Growth",
        source_path: "episodes/elena-verna/transcript.md",
        speaker: "Elena",
        timestamp: "00:01:00",
      },
    ];

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        target_chunk_id: 11,
        episode_id: 1,
        count: 2,
        chunks: mockContextChunks,
      }),
    });
    vi.stubGlobal("fetch", mockFetch);

    const tool = createGetTranscriptContextTool(collected, "http://mock-backend:8000", "test-token");
    const result = await tool.execute(
      "call-2",
      { chunk_id: 11, before: 1, after: 0 },
    );

    expect(collected.length).toBe(2);
    expect(result.content[0].text).toContain("Elena Verna");
    expect(result.content[0].text).toContain("[TARGET CHUNK]");
  });
});
