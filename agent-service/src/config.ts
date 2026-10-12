import dotenv from "dotenv";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Load .env from project root and agent-service directory
dotenv.config({ path: path.resolve(__dirname, "../../.env") });
dotenv.config({ path: path.resolve(process.cwd(), "../.env") });
dotenv.config({ path: path.resolve(process.cwd(), ".env") });
dotenv.config();

export interface AgentServiceConfig {
  port: number;
  host: string;
  backendUrl: string;
  agentInternalToken: string;
  modelProvider: string;
  modelId: string;
  modelBaseUrl: string;
  modelApiKey: string;
}

export function loadConfig(): AgentServiceConfig {
  const port = parseInt(process.env.PI_AGENT_PORT || process.env.PORT || "3000", 10);
  const host = process.env.HOST || process.env.PI_AGENT_HOST || "0.0.0.0";
  const backendUrl = process.env.BACKEND_URL || process.env.BACKEND_BASE_URL || "http://127.0.0.1:8000";
  const agentInternalToken =
    process.env.AGENT_INTERNAL_TOKEN || process.env.INTERNAL_TOKEN || "lenny-agent-internal-secret-token";


  const modelProvider =
    process.env.PI_AGENT_MODEL_PROVIDER || process.env.MODEL_PROVIDER || "ollama";
  const modelId = process.env.PI_AGENT_MODEL_ID || process.env.MODEL_ID || "qwen2.5:1.5b";
  const modelBaseUrl =
    process.env.PI_AGENT_MODEL_BASE_URL ||
    process.env.MODEL_BASE_URL ||
    "http://localhost:11434/v1";
  const modelApiKey =
    process.env.PI_AGENT_MODEL_API_KEY ||
    process.env.MODEL_API_KEY ||
    process.env.OPENAI_API_KEY ||
    (modelProvider === "ollama" ? "ollama-local" : "");

  return {
    port,
    host,
    backendUrl,
    agentInternalToken,
    modelProvider,
    modelId,
    modelBaseUrl,
    modelApiKey,
  };
}

export const config = loadConfig();
