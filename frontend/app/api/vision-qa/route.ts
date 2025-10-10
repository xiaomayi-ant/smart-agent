import { NextRequest } from "next/server";
import { withAuthHeaders } from "@/lib/withAuthHeaders";
// Use node runtime for stable piping of long-lived SSE
export const runtime = "nodejs";

export async function POST(request: NextRequest) {
  const backendBaseUrl = process.env["NEXT_PUBLIC_BACKEND_BASE_URL"] || "http://localhost:3001";
  const targetUrl = `${backendBaseUrl}/api/vision-qa/stream`;

  try {
    const formData = await request.formData();

    const headers = await withAuthHeaders();
    const res = await fetch(targetUrl, {
      method: "POST",
      body: formData,
      headers,
    });

    if (!res.ok) {
      const text = await res.text();
      return new Response(text, { status: res.status, headers: { "Content-Type": res.headers.get("Content-Type") || "text/plain" } });
    }

    // Stream through as-is (SSE)
    return new Response(res.body, {
      status: 200,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
      },
    });
  } catch (e: any) {
    return new Response(JSON.stringify({ error: { message: e?.message || "Proxy error" } }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }
}

export async function OPTIONS() {
  return new Response(null, {
    status: 204,
    headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, Authorization",
    },
  });
}

