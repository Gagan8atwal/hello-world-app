import { request as playwrightRequest } from "playwright-core";
import { randomBytes } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";

const BASE_URL = "https://omnimedia-engine.vercel.app";
const RUN_ID = (process.env.VERCEL_GIT_COMMIT_SHA || String(Date.now())).slice(0, 12);
const QA_EMAIL = `hello+vidgerexport-${RUN_ID}@pivotcalls.co`;
const QA_PASSWORD = `Vg!${randomBytes(30).toString("base64url")}9a`;
const MODEL = "fal-ai/kling-video/v3/standard/text-to-video";
const OUTPUT_DIR = resolve(process.cwd(), "public/showcase");
const VIDEO_DIR = join(OUTPUT_DIR, "videos");
const cases = [
  { id: "cinematic-real-movie", requestId: "01a03eb6-8a8e-7470-91bc-90a0da5b2618", duration: 5, description: "Photoreal cinematic movie shot" },
  { id: "premium-anime", requestId: "01a03eb6-8c66-7a93-9b37-42c5ab72cb08", duration: 5, description: "Premium hand-drawn anime shot" },
  { id: "history-map-to-rome", requestId: "01a03eb6-8c53-7c93-a3a8-2b0a7cff9aeb", duration: 10, description: "Historical map zoom into Roman Forum" },
];
const sleep = (ms) => new Promise((resolvePromise) => setTimeout(resolvePromise, ms));
async function readJson(response) { const text = await response.text(); try { return text ? JSON.parse(text) : {}; } catch { return { raw: text }; } }

async function signUp(api) {
  const response = await api.post("/api/auth", { headers: { "content-type": "application/json" }, data: { action: "signUp", email: QA_EMAIL, password: QA_PASSWORD, fullName: "Vidger Showcase Export QA" }, timeout: 30_000 });
  const payload = await readJson(response);
  if (!response.ok() || !payload.signedIn || !payload.user?.id) throw new Error(`QA signup failed ${response.status()}: ${JSON.stringify(payload)}`);
  await writeFile(join(OUTPUT_DIR, "qa-account.json"), JSON.stringify({ email: QA_EMAIL, userId: payload.user.id }, null, 2));
  console.log(`VIDGER_EXPORT_ACCOUNT email=${QA_EMAIL} userId=${payload.user.id}`);
  return payload.user.id;
}

async function waitForAccess(api) {
  const query = new URLSearchParams({ requestId: cases[0].requestId, model: MODEL });
  for (let attempt = 1; attempt <= 120; attempt += 1) {
    const response = await api.get(`/api/providers/fal/status?${query.toString()}`, { timeout: 30_000 }).catch(() => null);
    if (response?.ok()) { const payload = await readJson(response); if (payload.status === "COMPLETED" && payload.video?.url) { console.log(`VIDGER_EXPORT_ACCESS_READY email=${QA_EMAIL}`); return; } }
    if (attempt % 10 === 0) console.log(`VIDGER_EXPORT_WAITING_ACCESS email=${QA_EMAIL} attempt=${attempt}`);
    await sleep(3_000);
  }
  throw new Error("Export identity never received showcase access.");
}

async function exportCase(api, testCase) {
  const query = new URLSearchParams({ requestId: testCase.requestId, model: MODEL });
  const statusResponse = await api.get(`/api/providers/fal/status?${query.toString()}`, { timeout: 60_000 });
  const statusPayload = await readJson(statusResponse);
  if (!statusResponse.ok() || statusPayload.status !== "COMPLETED") throw new Error(`${testCase.id} status unavailable: ${statusResponse.status()} ${JSON.stringify(statusPayload)}`);
  const response = await api.get(`/api/providers/fal/export?${query.toString()}&branding=vidger&disposition=attachment`, { timeout: 360_000 });
  if (!response.ok()) throw new Error(`${testCase.id} branded export failed ${response.status()}: ${JSON.stringify(await readJson(response))}`);
  const bytes = await response.body();
  const output = join(VIDEO_DIR, `${testCase.id}-vidger.mp4`);
  await writeFile(output, bytes);
  const headers = response.headers();
  console.log(`VIDGER_EXPORT_COMPLETED case=${testCase.id} bytes=${bytes.length} branding=${headers["x-vidger-branding"] || "unknown"}`);
  return { ...testCase, status: "COMPLETED", bytes: bytes.length, contentType: headers["content-type"] || null, contentDisposition: headers["content-disposition"] || null, brandingHeader: headers["x-vidger-branding"] || null, file: `videos/${testCase.id}-vidger.mp4` };
}

async function main() {
  await Promise.all([mkdir(OUTPUT_DIR, { recursive: true }), mkdir(VIDEO_DIR, { recursive: true })]);
  const api = await playwrightRequest.newContext({ baseURL: BASE_URL, extraHTTPHeaders: { accept: "application/json" } });
  let exitCode = 1;
  try {
    const userId = await signUp(api);
    await waitForAccess(api);
    const results = [];
    for (const item of cases) results.push(await exportCase(api, item));
    const summary = { runId: RUN_ID, qaEmail: QA_EMAIL, qaUserId: userId, submittedNewGenerations: 0, completed: results.length, failed: 0, results };
    await writeFile(join(OUTPUT_DIR, "showcase-summary.json"), JSON.stringify(summary, null, 2));
    const cards = results.map((item) => `<article><h2>${item.description}</h2><video controls playsinline preload="metadata" src="./${item.file}"></video><p>${item.duration}s · Vidger branded · ${item.bytes} bytes</p><p><a href="./${item.file}">Open MP4</a></p></article>`).join("\n");
    await writeFile(join(OUTPUT_DIR, "index.html"), `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Vidger Production Showcase</title><style>body{font-family:system-ui;background:#080a0f;color:#f6f7fb;max-width:1100px;margin:30px auto;padding:0 16px}article{padding:18px;margin:18px 0;border:1px solid #273043;border-radius:16px;background:#10151f}video{display:block;width:100%;max-width:900px;background:#000;border-radius:12px}a{color:#a99cff}</style></head><body><h1>Vidger Production Showcase</h1>${cards}</body></html>`);
    exitCode = 0;
  } finally {
    await api.dispose().catch(() => null);
  }
  process.exit(exitCode);
}
main().catch(async (error) => { await mkdir(OUTPUT_DIR, { recursive: true }); await writeFile(join(OUTPUT_DIR, "fatal-error.txt"), error?.stack || String(error)); console.error(error); process.exit(1); });
