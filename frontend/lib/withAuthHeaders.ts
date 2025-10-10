import { cookies } from "next/headers";

export async function withAuthHeaders(extra?: Record<string, string>): Promise<Record<string, string>> {
  try {
    const jar = await cookies();
    const sid = jar.get("sid")?.value;
    const headers: Record<string, string> = { ...(extra || {}) };
    if (sid) headers["Authorization"] = `Bearer ${sid}`;
    return headers;
  } catch {
    return { ...(extra || {}) };
  }
}


