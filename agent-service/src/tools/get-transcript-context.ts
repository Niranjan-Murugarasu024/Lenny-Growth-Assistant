import { defineTool } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { config } from "../config.js";
import { InternalContextResponse, TranscriptChunkData } from "../types.js";

export function createGetTranscriptContextTool(
  collectedSources: TranscriptChunkData[],
  backendUrl: string = config.backendUrl,
  token: string = config.agentInternalToken,
) {
  return defineTool({
    name: "get_transcript_context",
    label: "Get Transcript Context",
    description:
      "Retrieve surrounding chronological transcript dialogue before and after a specific chunk ID within the same podcast episode.",
    parameters: Type.Object({
      chunk_id: Type.Number({
        description: "The unique ID of the transcript chunk to inspect context around.",
      }),
      before: Type.Optional(
        Type.Number({
          description: "Number of preceding chunks to retrieve (1-3, default 1).",
        }),
      ),
      after: Type.Optional(
        Type.Number({
          description: "Number of succeeding chunks to retrieve (1-3, default 1).",
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
      const before = Math.min(Math.max(params.before ?? 1, 0), 3);
      const after = Math.min(Math.max(params.after ?? 1, 0), 3);

      const endpoint = `${backendUrl}/internal/v1/transcripts/context`;
      try {
        const res = await fetch(endpoint, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Internal-Token": token,
          },
          body: JSON.stringify({
            chunk_id: params.chunk_id,
            before,
            after,
          }),
        });

        if (!res.ok) {
          const errText = await res.text();
          return {
            content: [
              {
                type: "text",
                text: `Context retrieval failed with status ${res.status}: ${errText}`,
              },
            ],
            details: { error: errText, status: res.status },
          };
        }

        const data = (await res.json()) as InternalContextResponse;
        const chunks = data.chunks || [];

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
                text: `No surrounding context found for chunk #${params.chunk_id}.`,
              },
            ],
            details: { chunk_id: params.chunk_id, count: 0, chunks: [] },
          };
        }

        const epTitle = chunks[0]?.title || "Unknown Episode";
        const epGuest = chunks[0]?.guest || "Unknown Guest";

        const formatted = chunks
          .map((c) => {
            const isTarget = c.chunk_id === params.chunk_id ? " [TARGET CHUNK]" : "";
            const timeStr = c.timestamp ? ` [${c.timestamp}]` : "";
            const spk = c.speaker ? ` (${c.speaker})` : "";
            return `Chunk #${c.chunk_id} (Index ${c.chunk_index})${isTarget}${timeStr}${spk}:\n${c.chunk_text}`;
          })
          .join("\n\n---\n\n");

        return {
          content: [
            {
              type: "text",
              text: `Chronological context for Chunk #${params.chunk_id} in "${epTitle}" (Guest: ${epGuest}):\n\n${formatted}`,
            },
          ],
          details: {
            target_chunk_id: params.chunk_id,
            count: chunks.length,
            chunks,
          },
        };
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        return {
          content: [
            {
              type: "text",
              text: `Error connecting to transcript context service: ${msg}`,
            },
          ],
          details: { error: msg },
        };
      }
    },
  });
}
