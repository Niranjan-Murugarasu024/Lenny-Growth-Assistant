import { createApp } from "./server.js";
import { config } from "./config.js";

const app = createApp();

const server = app.listen(config.port, config.host, () => {
  console.log(
    `[Lenny Pi Agent Service] Running on http://${config.host}:${config.port}`,
  );
  console.log(`Backend URL: ${config.backendUrl}`);
  console.log(`Model Provider: ${config.modelProvider} (${config.modelId})`);
});

process.on("SIGTERM", () => {
  console.log("SIGTERM received, shutting down gracefully...");
  server.close(() => process.exit(0));
});

process.on("SIGINT", () => {
  console.log("SIGINT received, shutting down gracefully...");
  server.close(() => process.exit(0));
});
