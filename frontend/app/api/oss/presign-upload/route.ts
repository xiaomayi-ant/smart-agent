import { NextRequest, NextResponse } from "next/server";
import { withAuthHeaders } from "@/lib/withAuthHeaders";
import { verifySession } from "@/lib/jwt";
import { createOssClient, buildObjectKey, signGetUrl } from "@/lib/oss";

export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  try {
    const headers = await withAuthHeaders({ "Content-Type": "application/json" });
    const sid = (headers["Authorization"] || "").replace(/^Bearer\s+/i, "");
    const userId = sid ? await verifySession(sid) : null;
    if (!userId) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

    const body = await req.json().catch(() => null) as { filename?: string; contentType?: string; category?: string } | null;
    const filename = (body?.filename || `file-${Date.now()}.bin`).toString();
    const contentType = (body?.contentType || "application/octet-stream").toString();
    const category: "images" | "audio" | "pdf" | "files" = ((): any => {
      if (contentType.startsWith("image/")) return "images";
      if (contentType.startsWith("audio/")) return "audio";
      if (contentType === "application/pdf") return "pdf";
      return "files";
    })();

    const key = buildObjectKey(filename, category);
    const client = createOssClient();
    const expiresSec = 600; // 10min for PUT

    // 预签名 PUT（直传）
    const putUrl = client.signatureUrl(key, {
      method: 'PUT',
      expires: expiresSec,
      // 设置内容类型，避免 OSS 识别为 application/octet-stream
      headers: { 'Content-Type': contentType },
    });

    // 预签名 GET（用于前端直接预览/发送给模型）
    const getSigned = await signGetUrl({ key, expiresSec: 3600, response: { 'response-content-type': contentType, 'response-content-disposition': 'inline' } });

    return NextResponse.json({
      key,
      putUrl,
      signedUrl: getSigned.url,
      signedUrlExpiresAt: getSigned.expiresAt,
      contentType,
    });
  } catch (e: any) {
    console.error('[API /api/oss/presign-upload] Error:', e);
    return NextResponse.json({ error: e?.message || 'Failed to presign upload' }, { status: 500 });
  }
}


