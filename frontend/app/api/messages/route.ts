import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { withAuthHeaders } from "@/lib/withAuthHeaders";
import { verifySession } from "@/lib/jwt";

export const runtime = "nodejs";

// GET /api/messages?conversationId=:id
export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url);
    const conversationId = searchParams.get("conversationId");
    if (!conversationId) {
      return NextResponse.json({ error: "conversationId is required" }, { status: 400 });
    }

    // 鉴权并限定会话归属
    const headers = await withAuthHeaders();
    const sid = (headers["Authorization"] || "").replace(/^Bearer\s+/i, "");
    const userId = sid ? await verifySession(sid) : null;
    if (!userId) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    // 校验会话是否存在且未归档
    const conv = await prisma.conversation.findFirst({
      where: { id: conversationId, archived: false, userId },
      select: { id: true, archived: true },
    });
    if (!conv) {
      return NextResponse.json({ error: "Conversation not found" }, { status: 404 });
    }

    const messages = await prisma.message.findMany({
      where: { conversationId, userId },
      orderBy: { createdAt: "asc" },
      select: { id: true, role: true, content: true, createdAt: true },
    });

    return NextResponse.json({ items: messages }, { status: 200 });
  } catch (e: any) {
    return NextResponse.json({ error: e?.message ?? "Internal Server Error" }, { status: 500 });
  }
}


