import { NextRequest, NextResponse } from "next/server";
import { withAuthHeaders } from "@/lib/withAuthHeaders";

export const runtime = "nodejs";

function isAllowed(url: URL) {
  return /\.aliyuncs\.com$/i.test(url.hostname);
}

export async function GET(req: NextRequest) {
  try {
    const fileId = req.nextUrl.searchParams.get("fileId");
    let targetUrl: string | null = null;
    if (fileId) {
      // 内部获取签名URL
      const base = req.nextUrl.origin;
      const headers = await withAuthHeaders();
      const resp = await fetch(`${base}/api/files/${encodeURIComponent(fileId)}`, { headers });
      if (!resp.ok) {
        const j = await resp.json().catch(() => ({} as any));
        return NextResponse.json({ error: j?.error || "failed to sign url" }, { status: 502 });
      }
      const data = await resp.json();
      targetUrl = data?.url || null;
      if (!targetUrl) return NextResponse.json({ error: "sign url empty" }, { status: 502 });
    } else {
      const u = req.nextUrl.searchParams.get("u");
      if (!u) return NextResponse.json({ error: "missing url or fileId" }, { status: 400 });
      targetUrl = u;
    }

    let target: URL;
    try { target = new URL(targetUrl); } catch { return NextResponse.json({ error: "invalid url" }, { status: 400 }); }
    if (!isAllowed(target)) return NextResponse.json({ error: "forbidden host" }, { status: 403 });

    const upstream = await fetch(target.toString(), { method: "GET" });
    if (!upstream.ok || !upstream.body) {
      const text = await upstream.text().catch(() => "");
      return NextResponse.json({ error: "upstream error", status: upstream.status, body: text.slice(0, 2000) }, { status: 502 });
    }

    // 透传内容类型（若缺失则回退为二进制流）
    const ct = upstream.headers.get("content-type") || "application/octet-stream";
    // 强制 inline 展示
    const disposition = "inline";

    const res = new NextResponse(upstream.body, {
      status: 200,
      headers: {
        "Content-Type": ct,
        "Cache-Control": "private, max-age=300",
        "Content-Disposition": disposition,
      },
    });
    return res;
  } catch (e: any) {
    return NextResponse.json({ error: e?.message || "proxy failed" }, { status: 500 });
  }
}


