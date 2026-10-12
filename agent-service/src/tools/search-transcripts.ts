import { defineTool } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { config } from "../config.js";
import { InternalSearchResponse, TranscriptChunkData } from "../types.js";

export function createSearchTranscriptsTool(
  collectedSources: TranscriptChunkData[],
  backendUrl: string = config.backendUrl,
  token: string = config.agentInternalToken,
) {
  return defineTool({
    name: "search_transcripts",
    label: "Search Transcripts",
    description:
      "Search Lenny's Podcast transcripts for relevant dialogue and insights. Returns transcript chunks with guest, title, timestamps, and text.",
    parameters: Type.Object({
      query: Type.String({
        description: "The search query describing the product, growth, or leadership topic to retrieve.",
      }),
      top_k: Type.Optional(
        Type.Number({
          description: "Maximum number of relevant chunks to retrieve (1-10, default 3).",
        }),
      ),
      max_distance: Type.Optional(
        Type.Number({
          description: "Maximum cosine distance threshold (default 0.30). Lower means more strictly relevant.",
        }),
      ),
    }),
    async execute(
      toolCallId,
      params,
    ): Promise<{
      content: Array<{ type: "text"; text: string }>;
      details: Record<string, unknown>;
    }> {
      const topK = Math.min(Math.max(params.top_k || 3, 1), 10);
      const maxDistance = params.max_distance ?? 0.30;

      const endpoint = `${backendUrl}/internal/v1/transcripts/search`;
      try {
        const res = await fetch(endpoint, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Internal-Token": token,
          },
          body: JSON.stringify({
            query: params.query,
            top_k: topK,
            max_distance: maxDistance,
          }),
        });

        if (!res.ok) {
          const errText = await res.text();
          return {
            content: [
              {
                type: "text",
                text: `Search failed with status ${res.status}: ${errText}`,
              },
            ],
            details: { error: errText, status: res.status },
          };
        }

        const data = (await res.json()) as InternalSearchResponse;
        const chunks = data.chunks || [];

        // Track collected sources uniquely by chunk_id
        for (const c of chunks) {
          if (!collectedSources.some((s) => s.chunk_id === c.chunk_id)) {
            collectedSources.push(c);
          }
        }

        if (chunks.length === 0) {
          return {
            content: [
              {
                type: "text",
                text: `No transcript passages found within relevance threshold for query: "${params.query}".`,
              },
            ],
            details: { query: params.query, count: 0, chunks: [] },
          };
        }

        const formatted = chunks
          .map((c, i) => {
            const timeStr = c.timestamp ? ` [${c.timestamp}]` : "";
            const spk = c.speaker ? ` (${c.speaker})` : "";
            return `[Source ${i + 1}] Episode: "${c.title}" | Guest: ${c.guest}${timeStr}${spk} (Chunk #${c.chunk_id}, distance: ${c.cosine_distance}):\n${c.chunk_text}`;
          })
          .join("\n\n---\n\n");

        return {
          content: [
            {
              type: "text",
              text: `Found ${chunks.length} transcript passages for "${params.query}":\n\n${formatted}`,
            },
          ],
          details: { query: params.query, count: chunks.length, chunks },
        };
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        return {
          content: [
            {
              type: "text",
              text: `Error connecting to transcript retrieval service: ${msg}`,
            },
          ],
          details: { error: msg },
        };
      }
    },
  });
}
