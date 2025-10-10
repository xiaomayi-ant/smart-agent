import { NextRequest, NextResponse } from "next/server";
import { withAuthHeaders } from "@/lib/withAuthHeaders";

export const runtime = "nodejs";

function isAllowed(url: URL) {
  // 仅允许阿里云 OSS 域名，避免 SSRF
  return /\.aliyuncs\.com$/i.test(url.hostname);
}

export async function GET(req: NextRequest) {
  try {
    const fileId = req.nextUrl.searchParams.get("fileId");
    let targetUrl: string | null = null;
    if (fileId) {
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

    // 计算文件名，供内置 PDF 查看器显示
    let filename = 'document.pdf';
    try {
      const seg = decodeURIComponent(target.pathname.split('/').pop() || 'document.pdf');
      filename = seg || 'document.pdf';
    } catch {}
    const encoded = encodeURIComponent(filename);

    const response = new NextResponse(upstream.body, {
      status: 200,
      headers: {
        "Content-Type": "application/pdf",
        "Cache-Control": "private, max-age=300",
        // 显式 inline 并携带文件名，便于浏览器查看器显示标题
        "Content-Disposition": `inline; filename="${encoded}"; filename*=UTF-8''${encoded}`,
      },
    });
    return response;
  } catch (e: any) {
    return NextResponse.json({ error: e?.message || "proxy failed" }, { status: 500 });
  }
}


