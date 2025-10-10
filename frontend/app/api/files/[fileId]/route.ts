import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { withAuthHeaders } from "@/lib/withAuthHeaders";
import { verifySession } from "@/lib/jwt";
import { signGetUrl } from "@/lib/oss";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ fileId: string }> }
) {
  try {
    const { fileId } = await params;
    if (!fileId) return NextResponse.json({ error: "No fileId provided" }, { status: 400 });

    const headers = await withAuthHeaders();
    const sid = (headers["Authorization"] || "").replace(/^Bearer\s+/i, "");
    const userId = sid ? await verifySession(sid) : null;
    if (!userId) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

    // 重要：在 RLS 生效前设置当前用户上下文
    try {
      await prisma.$executeRaw`select set_config('app.user_id', ${userId}, true)`;
    } catch {}

    // 读取文件元信息并校验归属
    const file = await prisma.file.findUnique({ where: { id: fileId }, select: { id: true, user_id: true, bucket: true, object_key: true, mime: true } });
    if (!file || file.user_id !== userId) return NextResponse.json({ error: "File not found" }, { status: 404 });

    // 生成签名URL（inline 以便预览）
    const { url, expiresAt } = await signGetUrl({
      key: file.object_key,
      expiresSec: 600,
      response: { 'response-content-type': file.mime || 'application/octet-stream', 'response-content-disposition': 'inline' },
    });

    return NextResponse.json({ url, expiresAt });

  } catch (error: any) {
    console.error("Signed URL error:", error);
    return NextResponse.json({ error: "Failed to generate signed URL", details: error.message }, { status: 500 });
  }
}

export async function OPTIONS() {
  return new NextResponse(null, {
    status: 204,
    headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    },
  });
}
