import { NextRequest, NextResponse } from "next/server";

const OWNER = "Gagan8atwal";
const REPO = "al-solutions-command-center";
const PATH = "alos-private-memory/data/brain.json";
const API = `https://api.github.com/repos/${OWNER}/${REPO}/contents/${PATH}`;

function headers() {
  const token = process.env.ALOS_GITHUB_TOKEN;
  if (!token) throw new Error("ALOS_GITHUB_TOKEN is not configured");
  return {
    Authorization: `Bearer ${token}`,
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "Content-Type": "application/json",
  };
}

export async function GET() {
  try {
    const response = await fetch(API, { headers: headers(), cache: "no-store" });
    if (!response.ok) {
      return NextResponse.json({ error: "Unable to load private memory" }, { status: response.status });
    }
    const file = await response.json();
    const json = Buffer.from(file.content, "base64").toString("utf8");
    return NextResponse.json({ data: JSON.parse(json), sha: file.sha });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Unknown error" }, { status: 500 });
  }
}

export async function PUT(request: NextRequest) {
  try {
    const { data, sha } = await request.json();
    if (!data || !Array.isArray(data.nodes) || !Array.isArray(data.links)) {
      return NextResponse.json({ error: "Invalid memory payload" }, { status: 400 });
    }

    const response = await fetch(API, {
      method: "PUT",
      headers: headers(),
      body: JSON.stringify({
        message: "chore: sync ALOS memory",
        content: Buffer.from(JSON.stringify(data, null, 2), "utf8").toString("base64"),
        sha,
        branch: "main",
      }),
    });

    const result = await response.json();
    if (!response.ok) {
      return NextResponse.json({ error: result.message || "Unable to save memory" }, { status: response.status });
    }

    return NextResponse.json({ ok: true, sha: result.content.sha });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Unknown error" }, { status: 500 });
  }
}
