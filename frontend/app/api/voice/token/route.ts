import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";
import { verifySession } from "@/lib/jwt";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const fetchCache = "force-no-store";

export async function GET(req: NextRequest) {
  try {
    const jar = await cookies();
    const sid = jar.get("sid")?.value || "";
    const userId = sid ? await verifySession(sid) : null;
    if (!userId) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    const serverKey = process.env.OPENAI_API_KEY || "";
    if (!serverKey) {
      return NextResponse.json({ error: "Missing OPENAI_API_KEY" }, { status: 500 });
    }

    const resp = await fetch("https://api.openai.com/v1/realtime/sessions", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${serverKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: "gpt-realtime",
        voice: "alloy",
      }),
    });

    if (!resp.ok) {
      const detail = await resp.text().catch(() => "");
      return NextResponse.json({ error: `OpenAI error ${resp.status}`, detail }, { status: 502 });
    }

    const data = (await resp.json().catch(() => ({}))) as any;
    const clientSecret =
      typeof data?.client_secret === "string"
        ? data.client_secret
        : data?.client_secret?.value || "";

    if (!clientSecret) {
      return NextResponse.json({ error: "No client_secret received" }, { status: 502 });
    }

    return NextResponse.json({ client_secret: clientSecret, expires_at: data?.expires_at || null });
  } catch (e: any) {
    return NextResponse.json({ error: e?.message ?? "Internal Server Error" }, { status: 500 });
  }
}


