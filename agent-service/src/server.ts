import express, { Request, Response } from "express";
import { config } from "./config.js";
import { runAgent, verifyToolConfiguration } from "./agent.js";
import { AgentRunRequest } from "./types.js";

export function createApp() {
  const app = express();
  app.use(express.json({ limit: "5mb" }));

  // 1. Fast liveness probe
  app.get("/health/live", (req: Request, res: Response) => {
    res.status(200).json({
      status: "ok",
      service: "lenny-pi-agent",
      timestamp: new Date().toISOString(),
    });
  });

  // 2. Readiness probe checking backend connectivity, tool verification, and model configuration
  app.get("/health/ready", async (req: Request, res: Response) => {
    let backendStatus = "unknown";
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 3000);
      const backendRes = await fetch(`${config.backendUrl}/health/live`, {
        signal: controller.signal,
      });
      clearTimeout(timeoutId);
      backendStatus = backendRes.ok ? "connected" : `error_${backendRes.status}`;
    } catch {
      backendStatus = "disconnected";
    }

    let toolVerification: { activeTools: string[]; allTools: string[]; valid: boolean; reason?: string };
    try {
      toolVerification = await verifyToolConfiguration();
    } catch (err) {
      toolVerification = {
        activeTools: [],
        allTools: [],
        valid: false,
        reason: err instanceof Error ? err.message : String(err),
      };
    }

    const isReady = backendStatus === "connected" && toolVerification.valid;
    const statusCode = isReady ? 200 : 503;

    res.status(statusCode).json({
      status: isReady ? "ready" : "not_ready",
      backend: {
        url: config.backendUrl,
        status: backendStatus,
      },
      tools: {
        status: toolVerification.valid ? "verified" : "invalid",
        active: toolVerification.activeTools,
        all_registered: toolVerification.allTools,
        builtins_disabled: true,
        extensions_disabled: true,
        reason: toolVerification.reason,
      },
      model: {
        provider: config.modelProvider,
        id: config.modelId,
        base_url: config.modelBaseUrl,
      },
    });
  });

  // 3. Agent execution endpoint
  app.post("/v1/agent/run", async (req: Request, res: Response) => {
    const body = req.body as Partial<AgentRunRequest>;
    if (!body || !body.question || !body.question.trim()) {
      return res.status(400).json({
        error: {
          code: "INVALID_REQUEST",
          message: "Request must include a non-empty 'question' string.",
        },
      });
    }

    try {
      const response = await runAgent({
        question: body.question.trim(),
        history: body.history || [],
        request_id: body.request_id,
      });

      res.status(200).json(response);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error("Agent execution error:", err);
      res.status(500).json({
        error: {
          code: "AGENT_EXECUTION_ERROR",
          message: `Agent execution failed: ${msg}`,
          request_id: body.request_id,
        },
      });
    }
  });

  return app;
}
