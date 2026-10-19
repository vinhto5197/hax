import { defineConfig, devices } from "@playwright/test";

// The isolated stack `make e2e` runs against. The dev shell exports the root
// .env (direnv) into every child process, so each variable that selects a
// database, Redis, the model, a secret, a URL or a port is set here, or a
// server would quietly reach dev data. e2e/prepare.py owns the same database
// and Redis db and must run first.
const WEB_URL = "http://localhost:3001";
const API_URL = "http://localhost:8001";
const FAKE_MODEL_URL = "http://localhost:8787";

// Shared by the API and the web: Auth.js mints with AUTH_SECRET and FastAPI
// verifies with it; INTERNAL_API_SECRET gates Next's server-to-server calls.
// Plain http, so Auth.js names the cookie without the __Secure- prefix.
const E2E_ENV = {
  AUTH_SECRET: "e2e-auth-secret-not-for-real-use-padded",
  INTERNAL_API_SECRET: "e2e-internal-secret-not-for-real-use",
  AUTH_COOKIE_NAME: "authjs.session-token",
};

export default defineConfig({
  testDir: "./e2e",
  testMatch: /.*\.(spec|setup)\.ts/,
  workers: 1,
  fullyParallel: false,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: { baseURL: WEB_URL, trace: "retain-on-failure" },
  projects: [
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    {
      name: "guest",
      testMatch: /.*\.guest\.spec\.ts/,
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "member",
      testMatch: /.*\.member\.spec\.ts/,
      dependencies: ["setup"],
      use: {
        ...devices["Desktop Chrome"],
        storageState: "e2e/.auth/member.json",
      },
    },
  ],
  webServer: [
    {
      command: "node e2e/fake-model/server.mjs",
      url: `${FAKE_MODEL_URL}/`,
      env: { FAKE_MODEL_PORT: "8787" },
      reuseExistingServer: false,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command:
        "cd ../.. && .venv/bin/python -m uvicorn apps.api.main:app --port 8001",
      url: `${API_URL}/api/health`,
      env: {
        ...E2E_ENV,
        DATABASE_URL: "postgresql://hax_app:hax_app@localhost:5432/hax_e2e",
        MIGRATIONS_DATABASE_URL: "postgresql://hax:hax@localhost:5432/hax_e2e",
        REDIS_URL: "redis://localhost:6379/15",
        ANTHROPIC_BASE_URL: FAKE_MODEL_URL,
        ANTHROPIC_API_KEY: "fake",
        VOYAGE_API_KEY: "fake",
        LLM_MODEL: "claude-haiku-4-5",
        TITLE_MODEL: "claude-haiku-4-5",
        CORS_ALLOW_ORIGINS: WEB_URL,
        APP_BASE_URL: WEB_URL,
        LOG_LEVEL: "INFO",
        // No journey uploads or sends mail: unroutable endpoints, so a stray
        // call fails fast instead of reaching dev MinIO or Mailpit.
        S3_ENDPOINT_URL: "http://localhost:1",
        S3_BUCKET: "hax-e2e",
        S3_REGION: "us-east-1",
        S3_ACCESS_KEY_ID: "e2e",
        S3_SECRET_ACCESS_KEY: "e2e-not-a-secret",
        SMTP_HOST: "localhost",
        SMTP_PORT: "1",
        SMTP_FROM: "e2e@example.com",
        SMTP_USER: "",
        SMTP_PASSWORD: "",
        EMAIL_RECIPIENT: "e2e@example.com",
        BOOTSTRAP_USER_EMAIL: "",
        AUTH_REQUIRE_EMAIL_VERIFICATION: "true",
        DEMO_TURN_LIMIT: "3",
        // Every guest journey signs in anonymously from the same address; a
        // journey that tests the cap sets its own value.
        ANON_PER_IP_PER_DAY: "1000",
        ANON_RETENTION_DAYS: "3",
      },
      reuseExistingServer: false,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: "npm run build && npx next start -p 3001",
      url: `${WEB_URL}/`,
      timeout: 180_000,
      env: {
        ...E2E_ENV,
        NEXT_PUBLIC_API_URL: API_URL,
        API_INTERNAL_URL: API_URL,
        AUTH_URL: WEB_URL,
        AUTH_TRUST_HOST: "true",
        AUTH_GOOGLE_ID: "e2e-unused",
        AUTH_GOOGLE_SECRET: "e2e-unused",
      },
      reuseExistingServer: false,
      stdout: "pipe",
      stderr: "pipe",
    },
  ],
});
