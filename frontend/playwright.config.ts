import { defineConfig, devices } from "@playwright/test";

const backendPython = "../backend/.venv/bin/python";

export default defineConfig({
  testDir: "e2e",
  timeout: 90_000,
  expect: { timeout: 20_000 },
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "on-first-retry",
  },
  webServer: [
    {
      command: `${backendPython} -m uvicorn app.main:app --host 127.0.0.1 --port 8000`,
      cwd: "../backend",
      url: "http://127.0.0.1:8000/api/health",
      reuseExistingServer: false,
      env: {
        FRAMEFIT_MODE: "demo",
        FRAMEFIT_WORKER: "1",
        SECRET_KEY: "e2e-secret",
        DATABASE_URL: "sqlite:///./data/e2e.db",
        LOCAL_STORAGE_DIR: "./data/e2e-assets",
        YOLO_CACHE_DIR: "./data/e2e-models",
        FRONTEND_ORIGINS: "http://127.0.0.1:5173,http://localhost:5173",
        RATE_LIMIT_PER_MINUTE: "10000",
      },
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5173 --strictPort",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: false,
    },
  ],
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
