import { SignJWT, jwtVerify } from "jose";

const secret = new TextEncoder().encode(process.env.JWT_SECRET || "");

export async function signSession(userId: string, maxAgeSec = 30 * 24 * 3600): Promise<string> {
  const now = Math.floor(Date.now() / 1000);
  return new SignJWT({})
    .setProtectedHeader({ alg: "HS256", typ: "JWT" })
    .setSubject(userId)
    .setIssuedAt(now)
    .setExpirationTime(now + maxAgeSec)
    .sign(secret);
}

export async function verifySession(token: string): Promise<string | null> {
  try {
    const { payload } = await jwtVerify(token, secret);
    return payload?.sub ? String(payload.sub) : null;
  } catch {
    return null;
  }
}


