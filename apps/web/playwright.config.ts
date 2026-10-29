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

// The API and the workers run on this one object, so the process that accepts
// an upload and the one that ingests it can never disagree on the database,
// the broker, storage, the model or the chunking.
const SERVER_ENV = {
  ...E2E_ENV,
  DATABASE_URL: "postgresql://hax_app:hax_app@localhost:5432/hax_e2e",
  MIGRATIONS_DATABASE_URL: "postgresql://hax:hax@localhost:5432/hax_e2e",
  REDIS_URL: "redis://localhost:6379/15",
  ANTHROPIC_BASE_URL: FAKE_MODEL_URL,
  ANTHROPIC_API_KEY: "fake",
  VOYAGE_BASE_URL: `${FAKE_MODEL_URL}/v1`,
  VOYAGE_API_KEY: "fake",
  LLM_MODEL: "claude-haiku-4-5",
  TITLE_MODEL: "claude-haiku-4-5",
  // Pinned so a developer's .env cannot change how many chunks a document
  // makes or how many a search returns; the journeys count both.
  RAG_TOP_K: "5",
  RAG_CHUNK_SIZE: "1600",
  RAG_CHUNK_OVERLAP: "200",
  RAG_MAX_DISTANCE: "",
  CORS_ALLOW_ORIGINS: WEB_URL,
  APP_BASE_URL: WEB_URL,
  LOG_LEVEL: "INFO",
  // The dev S3 stand-in from `make infra-up` (a service container in CI) in a
  // bucket of its own; dev's hax-documents is never touched. Leftover objects
  // are never emptied: keys are unique per document and prepare.py truncates
  // the database, so nothing references them.
  S3_ENDPOINT_URL: "http://localhost:9000",
  S3_BUCKET: "hax-e2e",
  S3_REGION: "us-east-1",
  S3_ACCESS_KEY_ID: "hax",
  S3_SECRET_ACCESS_KEY: "haxhaxhax",
  // No journey reads mail: an unroutable port, so the fast worker's sends fail
  // and retry in its log instead of reaching dev Mailpit.
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
      env: SERVER_ENV,
      reuseExistingServer: false,
      stdout: "pipe",
      stderr: "pipe",
    },
    // One worker per queue, as `make worker-ingest` and `make worker-fast`
    // run them, and no beat; a title never waits behind an ingestion. Solo
    // pool: the prefork pool crashes every task on macOS.
    {
      command:
        "cd ../.. && .venv/bin/celery -A apps.worker.celery_app worker -Q ingest --pool=solo -l INFO",
      wait: { stderr: /ready\./ },
      env: SERVER_ENV,
      timeout: 60_000,
      reuseExistingServer: false,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command:
        "cd ../.. && .venv/bin/celery -A apps.worker.celery_app worker -Q celery --pool=solo -l INFO",
      wait: { stderr: /ready\./ },
      env: SERVER_ENV,
      timeout: 60_000,
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
