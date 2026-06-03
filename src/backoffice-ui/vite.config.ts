import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// The backoffice is served behind the proxy under the /backoffice path prefix,
// so its built asset URLs must carry that base. nginx maps the prefix to the
// static bundle (see nginx.conf).
const TEN_MIN = 600_000;

export default defineConfig({
  base: "/backoffice/",
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
