import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { signSession, verifySession } from "@/lib/jwt";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const jar = await cookies();
  const maxAge = 30 * 24 * 3600; // 30 days
  const existing = jar.get("sid")?.value;

  if (existing) {
    const uid = await verifySession(existing);
    if (uid) {
      const newToken = await signSession(uid, maxAge);
      const res = NextResponse.json({ ok: true, userId: uid });
      res.cookies.set("sid", newToken, {
        httpOnly: true,
        secure: process.env.NODE_ENV === "production",
        sameSite: "lax",
        path: "/",
        maxAge,
      });
      return res;
    }
  }

  const userId = typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `u_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;

  const token = await signSession(userId, maxAge);
  const res = NextResponse.json({ ok: true, userId });
  res.cookies.set("sid", token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge,
  });
  return res;
}


