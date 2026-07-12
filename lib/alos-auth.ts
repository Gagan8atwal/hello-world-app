import crypto from "node:crypto";
import { cookies } from "next/headers";

const COOKIE_NAME = "alos_session";

function expectedSession(): string {
  const accessKey = process.env.ALOS_ACCESS_KEY;
  const signingKey = process.env.ALOS_SESSION_SECRET;
  if (!accessKey || !signingKey) return "";
  return crypto.createHmac("sha256", signingKey).update(accessKey).digest("hex");
}

export async function isAuthorized(): Promise<boolean> {
  const jar = await cookies();
  const supplied = jar.get(COOKIE_NAME)?.value ?? "";
  const expected = expectedSession();
  if (!supplied || !expected || supplied.length !== expected.length) return false;
  return crypto.timingSafeEqual(Buffer.from(supplied), Buffer.from(expected));
}

export function createSessionValue(): string {
  return expectedSession();
}

export const sessionCookieName = COOKIE_NAME;
