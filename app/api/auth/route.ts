import { NextResponse } from "next/server";
import crypto from "node:crypto";
import { createSessionValue, sessionCookieName } from "@/lib/alos-auth";

export async function POST(request: Request) {
  const body = await request.json().catch(() => ({}));
  const supplied = typeof body?.accessKey === "string" ? body.accessKey : "";
  const expected = process.env.ALOS_ACCESS_KEY ?? "";

  if (!supplied || !expected || supplied.length !== expected.length) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const valid = crypto.timingSafeEqual(Buffer.from(supplied), Buffer.from(expected));
  if (!valid) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const response = NextResponse.json({ ok: true });
  response.cookies.set(sessionCookieName, createSessionValue(), {
    httpOnly: true,
    secure: true,
    sameSite: "strict",
    path: "/",
    maxAge: 60 * 60 * 24 * 30
  });
  return response;
}

export async function DELETE() {
  const response = NextResponse.json({ ok: true });
  response.cookies.set(sessionCookieName, "", {
    httpOnly: true,
    secure: true,
    sameSite: "strict",
    path: "/",
    maxAge: 0
  });
  return response;
}
