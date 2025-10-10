import { NextRequest, NextResponse } from "next/server";
import { withAuthHeaders } from "@/lib/withAuthHeaders";

export const runtime = "nodejs";

function getLangGraphApiBase(): string {
  const base = process.env["LANGGRAPH_API_URL"];
  if (!base) throw new Error("LANGGRAPH_API_URL is not configured");
  const trimmed = base.replace(/\/$/, "");
  return trimmed.endsWith("/api") ? trimmed : `${trimmed}/api`;
}

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => null)) as any;
  if (!body || typeof body !== "object") {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }
  const threadId = typeof body.threadId === "string" ? body.threadId : null;
  if (!threadId) {
    return NextResponse.json({ error: "threadId is required" }, { status: 400 });
  }
  const headers = await withAuthHeaders({ "Content-Type": "application/json" });
  const upstream = await fetch(`${getLangGraphApiBase()}/threads/${encodeURIComponent(threadId)}/tools/approval`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      toolName: body.toolName,
      args: body.args,
      approve: !!body.approve,
      toolCallId: body.toolCallId,
    }),
  });
  const data = await upstream.json().catch(() => ({}));
  return NextResponse.json(data, { status: upstream.status });
}


