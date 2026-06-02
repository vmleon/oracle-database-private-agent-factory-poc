import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// The backend chat turn runs for minutes; the SSE stream can sit silent between
// "open" and the "agent" event, so the proxy read timeout must exceed a turn.
const TEN_MIN = 600_000;

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": new URL("./src", import.meta.url).pathname },
  },
  server: {
    proxy: {
      "/v1": {
        target: "http://localhost:8090",
        changeOrigin: true,
        timeout: TEN_MIN,
        proxyTimeout: TEN_MIN,
      },
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
