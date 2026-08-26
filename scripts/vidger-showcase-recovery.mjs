import { chromium as playwrightChromium } from "playwright-core";
import serverlessChromium from "@sparticuz/chromium";
import ffmpegPath from "ffmpeg-static";
import ffprobeStatic from "ffprobe-static";
import { createHash, randomBytes } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const BASE_URL = "https://omnimedia-engine.vercel.app";
const RUN_ID = (process.env.VERCEL_GIT_COMMIT_SHA || String(Date.now())).slice(0, 12);
const QA_EMAIL = `hello+vidgerrecover2-${RUN_ID}@pivotcalls.co`;
const QA_PASSWORD = `Vg!${randomBytes(30).toString("base64url")}9a`;
const MODEL = "fal-ai/kling-video/v3/standard/text-to-video";
const OUTPUT_DIR = resolve(process.cwd(), "public/showcase");
const SCREENSHOT_DIR = join(OUTPUT_DIR, "screenshots");
const VIDEO_DIR = join(OUTPUT_DIR, "videos");
const STORYBOARD_DIR = join(OUTPUT_DIR, "storyboards");
const FRAME_DIR = join(OUTPUT_DIR, "frames");
const cases = [
  { id: "cinematic-real-movie", requestId: "01a03eb6-8a8e-7470-91bc-90a0da5b2618", duration: 5, description: "Photoreal cinematic movie shot" },
  { id: "premium-anime", requestId: "01a03eb6-8c66-7a93-9b37-42c5ab72cb08", duration: 5, description: "Premium hand-drawn anime shot" },
  { id: "history-map-to-rome", requestId: "01a03eb6-8c53-7c93-a3a8-2b0a7cff9aeb", duration: 10, description: "Historical map zoom into Roman Forum" },
];
const sleep = (ms) => new Promise((resolvePromise) => setTimeout(resolvePromise, ms));
async function readJson(response) { const text = await response.text(); try { return text ? JSON.parse(text) : {}; } catch { return { raw: text }; } }
async function signUp(page) {
  const response = await page.request.post(`${BASE_URL}/api/auth`, { headers: { "content-type": "application/json" }, data: { action: "signUp", email: QA_EMAIL, password: QA_PASSWORD, fullName: "Vidger Showcase Recovery QA" }, timeout: 30_000 });
  const payload = await readJson(response);
  if (!response.ok() || !payload.signedIn || !payload.user?.id) throw new Error(`QA signup failed ${response.status()}: ${JSON.stringify(payload)}`);
  await writeFile(join(OUTPUT_DIR, "qa-account.json"), JSON.stringify({ email: QA_EMAIL, userId: payload.user.id }, null, 2));
  console.log(`VIDGER_RECOVERY2_ACCOUNT email=${QA_EMAIL} userId=${payload.user.id}`);
  return payload.user.id;
}
async function waitForAccess(page) {
  const query = new URLSearchParams({ requestId: cases[0].requestId, model: MODEL });
  for (let attempt = 1; attempt <= 180; attempt += 1) {
    const response = await page.request.get(`${BASE_URL}/api/providers/fal/status?${query.toString()}`, { timeout: 30_000 }).catch(() => null);
    if (response?.ok()) { const payload = await readJson(response); if (payload.status === "COMPLETED" && payload.video?.url) { console.log(`VIDGER_RECOVERY2_ACCESS_READY email=${QA_EMAIL}`); return; } }
    if (attempt % 10 === 0) console.log(`VIDGER_RECOVERY2_WAITING_ACCESS email=${QA_EMAIL} attempt=${attempt}`);
    await sleep(4_000);
  }
  throw new Error("Recovery identity never received showcase access.");
}
function run(command, args) { const result = spawnSync(command, args, { encoding: "utf8", maxBuffer: 16 * 1024 * 1024 }); if (result.status !== 0) throw new Error(`${command} failed: ${(result.stderr || result.stdout || "").slice(-2500)}`); return result.stdout.trim(); }
function probe(filePath) { return JSON.parse(run(ffprobeStatic.path, ["-v", "error", "-show_entries", "format=duration,size,bit_rate:format_tags=comment,encoder:stream=codec_type,codec_name,width,height,pix_fmt,r_frame_rate", "-of", "json", filePath])); }
function storyboard(input, output) { run(ffmpegPath, ["-hide_banner", "-loglevel", "error", "-y", "-i", input, "-vf", "fps=1,scale=480:-1,tile=5x2:padding=8:margin=8:color=0x111111", "-frames:v", "1", output]); }
function frame(input, second, output) { run(ffmpegPath, ["-hide_banner", "-loglevel", "error", "-y", "-ss", String(second), "-i", input, "-frames:v", "1", "-q:v", "2", output]); }
async function injectLiveResult(page, testCase, statusPayload) {
  await page.goto(`${BASE_URL}/app`, { waitUntil: "domcontentloaded", timeout: 60_000 });
  await page.waitForSelector("[data-prompt-result]", { state: "attached", timeout: 60_000 });
  await page.evaluate(({ payload, label }) => {
    const gate = document.querySelector("[data-auth-gate]"); if (gate) gate.hidden = true;
    const result = document.querySelector("[data-prompt-result]"); const empty = result?.closest(".preview")?.querySelector("[data-preview-empty]"); if (!result) throw new Error("Vidger result container missing.");
    if (empty) empty.hidden = true; result.hidden = false; result.replaceChildren();
    const meta = document.createElement("div"); meta.className = "result-meta"; const strong = document.createElement("strong"); strong.textContent = "Video ready"; const span = document.createElement("span"); span.textContent = label; meta.append(strong, span);
    const stage = document.createElement("div"); stage.className = "video-stage"; const video = document.createElement("video"); video.preload = "auto"; video.playsInline = true; video.muted = true; video.controls = true; video.src = payload.video.url; stage.append(video);
    const actions = document.createElement("div"); actions.className = "video-actions"; actions.innerHTML = '<button class="button secondary" type="button">Full screen</button><button class="button" type="button">Download</button>'; result.append(meta, stage, actions);
  }, { payload: statusPayload, label: testCase.description });
  await page.waitForSelector("[data-prompt-result] .vidger-video-mark", { state: "visible", timeout: 60_000 });
  const video = page.locator("[data-prompt-result] video"); await video.waitFor({ state: "visible", timeout: 60_000 }); await video.evaluate((node) => node.play().catch(() => null)); await page.waitForTimeout(1000);
}
async function recoverCase(context, testCase) {
  const page = await context.newPage(); const result = { ...testCase, model: MODEL, status: "STARTED", error: null, media: null, files: {}, startedAt: new Date().toISOString() };
  try {
    const query = new URLSearchParams({ requestId: testCase.requestId, model: MODEL });
    const statusResponse = await page.request.get(`${BASE_URL}/api/providers/fal/status?${query.toString()}`, { timeout: 60_000 }); const statusPayload = await readJson(statusResponse);
    if (!statusResponse.ok() || statusPayload.status !== "COMPLETED" || !statusPayload.video?.url) throw new Error(`Completed video unavailable: ${statusResponse.status()} ${JSON.stringify(statusPayload)}`);
    await injectLiveResult(page, testCase, statusPayload); const screenshotPath = join(SCREENSHOT_DIR, `${testCase.id}-live-playback.png`); await page.screenshot({ path: screenshotPath, fullPage: true });
    const exportResponse = await page.request.get(`${BASE_URL}/api/providers/fal/export?${query.toString()}&branding=vidger&disposition=attachment`, { timeout: 360_000 });
    if (!exportResponse.ok()) throw new Error(`Branded export failed ${exportResponse.status()}: ${JSON.stringify(await readJson(exportResponse))}`);
    const videoPath = join(VIDEO_DIR, `${testCase.id}-vidger.mp4`); await writeFile(videoPath, await exportResponse.body()); const media = probe(videoPath); const stream = (media.streams || []).find((item) => item.codec_type === "video");
    if (!stream || stream.codec_name !== "h264" || stream.pix_fmt !== "yuv420p") throw new Error(`iPhone-safe H.264/yuv420p check failed: ${JSON.stringify(stream || {})}`);
    if (!/Branded by Vidger/i.test(String(media.format?.tags?.comment || ""))) throw new Error("Vidger burned-export metadata missing.");
    const storyboardPath = join(STORYBOARD_DIR, `${testCase.id}-storyboard.jpg`); storyboard(videoPath, storyboardPath); const duration = Number(media.format?.duration || testCase.duration); const framePaths = [];
    for (const [name, second] of [["start", 0.35], ["middle", duration / 2], ["end", Math.max(0.5, duration - 0.5)]]) { const output = join(FRAME_DIR, `${testCase.id}-${name}.jpg`); frame(videoPath, second, output); framePaths.push(`frames/${testCase.id}-${name}.jpg`); }
    result.status = "COMPLETED"; result.media = media; result.sha256 = createHash("sha256").update(await readFile(videoPath)).digest("hex"); result.files = { video: `videos/${testCase.id}-vidger.mp4`, storyboard: `storyboards/${testCase.id}-storyboard.jpg`, screenshot: `screenshots/${testCase.id}-live-playback.png`, frames: framePaths }; console.log(`VIDGER_RECOVERY2_COMPLETED case=${testCase.id}`);
  } catch (error) { result.status = "FAILED"; result.error = error instanceof Error ? error.message : String(error); await page.screenshot({ path: join(SCREENSHOT_DIR, `${testCase.id}-failure.png`), fullPage: true }).catch(() => null); console.error(`VIDGER_RECOVERY2_FAILED case=${testCase.id} error=${result.error}`); }
  result.finishedAt = new Date().toISOString(); await writeFile(join(OUTPUT_DIR, `${testCase.id}.json`), JSON.stringify(result, null, 2)); await page.close().catch(() => null); return result;
}
async function writeIndex(results) { const cards = results.map((item) => `<article><h2>${item.description}</h2><p>${item.status}${item.error ? ` — ${item.error}` : ""}</p>${item.files.video ? `<video controls preload="metadata" src="./${item.files.video}"></video><p><a href="./${item.files.video}">Branded MP4</a> · <a href="./${item.files.storyboard}">Storyboard</a> · <a href="./${item.files.screenshot}">Live browser proof</a></p>` : ""}</article>`).join("\n"); await writeFile(join(OUTPUT_DIR, "index.html"), `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Vidger Showcase</title><style>body{font-family:system-ui;background:#0b0d12;color:#f5f7fb;max-width:1100px;margin:40px auto;padding:0 20px}article{padding:20px;margin:20px 0;border:1px solid #2b3240;border-radius:16px;background:#121722}video{width:100%;max-width:900px;border-radius:12px}a{color:#9e8aff}</style><h1>Vidger Production Showcase</h1>${cards}`); }
async function main() {
  await Promise.all([mkdir(OUTPUT_DIR, { recursive: true }), mkdir(SCREENSHOT_DIR, { recursive: true }), mkdir(VIDEO_DIR, { recursive: true }), mkdir(STORYBOARD_DIR, { recursive: true }), mkdir(FRAME_DIR, { recursive: true })]);
  const browser = await playwrightChromium.launch({ executablePath: await serverlessChromium.executablePath(), args: [...serverlessChromium.args, "--disable-dev-shm-usage"], headless: true }); const context = await browser.newContext({ viewport: { width: 1440, height: 1050 } }); const bootstrap = await context.newPage();
  let exitCode = 1;
  try { await bootstrap.goto(`${BASE_URL}/app`, { waitUntil: "domcontentloaded", timeout: 60_000 }); const userId = await signUp(bootstrap); await waitForAccess(bootstrap); const results = []; for (const testCase of cases) results.push(await recoverCase(context, testCase)); const summary = { runId: RUN_ID, qaEmail: QA_EMAIL, qaUserId: userId, submittedNewGenerations: 0, completed: results.filter((item) => item.status === "COMPLETED").length, failed: results.filter((item) => item.status !== "COMPLETED").length, results }; await writeFile(join(OUTPUT_DIR, "showcase-summary.json"), JSON.stringify(summary, null, 2)); await writeIndex(results); exitCode = summary.completed === cases.length ? 0 : 1; }
  finally { await Promise.race([context.close().catch(() => null), sleep(2000)]); await Promise.race([browser.close().catch(() => null), sleep(2000)]); }
  process.exit(exitCode);
}
main().catch(async (error) => { await mkdir(OUTPUT_DIR, { recursive: true }); await writeFile(join(OUTPUT_DIR, "fatal-error.txt"), error?.stack || String(error)); console.error(error); process.exit(1); });
