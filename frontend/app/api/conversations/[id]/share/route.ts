import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";

export const runtime = "nodejs";

// POST /api/conversations/[id]/share - 生成分享链接
export async function POST(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await params;
    if (!id) return NextResponse.json({ error: "id is required" }, { status: 400 });
    
    // 检查会话是否存在
    const conv = await prisma.conversation.findUnique({
      where: { id },
      select: { id: true, title: true, archived: true },
    });
    
    if (!conv) {
      return NextResponse.json({ error: "Conversation not found" }, { status: 404 });
    }
    
    if (conv.archived) {
      return NextResponse.json({ error: "Cannot share archived conversation" }, { status: 400 });
    }
    
    // 生成分享URL（这里可以扩展为更复杂的分享机制，比如生成临时token等）
    const shareUrl = `${process.env.NEXT_PUBLIC_APP_URL || 'http://localhost:3000'}/chat/${id}`;
    
    return NextResponse.json({
      shareUrl,
      title: conv.title,
      id: conv.id,
    });
  } catch (e: any) {
    return NextResponse.json({ error: e?.message ?? "Internal Server Error" }, { status: 500 });
  }
}
