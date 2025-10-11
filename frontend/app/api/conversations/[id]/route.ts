import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { withAuthHeaders } from "@/lib/withAuthHeaders";
import { verifySession } from "@/lib/jwt";

export const runtime = "nodejs";

export async function GET(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await params;
    if (!id) return NextResponse.json({ error: "id is required" }, { status: 400 });
    const headers = await withAuthHeaders();
    const sid = (headers["Authorization"] || "").replace(/^Bearer\s+/i, "");
    const userId = sid ? await verifySession(sid) : null;
    if (!userId) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

    const conv = await prisma.conversation.findFirst({
      where: { id, userId },
      select: { id: true, title: true, updatedAt: true, threadId: true, archived: true, createdAt: true },
    });
    if (!conv) return NextResponse.json({ error: "Not found" }, { status: 404 });
    return NextResponse.json(conv);
  } catch (e: any) {
    return NextResponse.json({ error: e?.message ?? "Internal Server Error" }, { status: 500 });
  }
}

// PATCH /api/conversations/[id] - 更新会话状态（如归档）
export async function PATCH(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await params;
    if (!id) return NextResponse.json({ error: "id is required" }, { status: 400 });
    
    const headers = await withAuthHeaders();
    const sid = (headers["Authorization"] || "").replace(/^Bearer\s+/i, "");
    const userId = sid ? await verifySession(sid) : null;
    if (!userId) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    
    const body = await req.json().catch(() => ({}));
    
    if (body.action === 'archive') {
      const conv = await prisma.conversation.update({
        where: { id, userId },
        data: { archived: true },
        select: { id: true, title: true, archived: true, updatedAt: true },
      });
      return NextResponse.json(conv);
    }
    
    if (body.action === 'unarchive') {
      const conv = await prisma.conversation.update({
        where: { id, userId },
        data: { archived: false },
        select: { id: true, title: true, archived: true, updatedAt: true },
      });
      return NextResponse.json(conv);
    }
    
    return NextResponse.json({ error: "Invalid action. Supported: archive, unarchive" }, { status: 400 });
  } catch (e: any) {
    return NextResponse.json({ error: e?.message ?? "Internal Server Error" }, { status: 500 });
  }
}

// DELETE /api/conversations/[id] - 永久删除会话
export async function DELETE(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await params;
    if (!id) return NextResponse.json({ error: "id is required" }, { status: 400 });

    const headers = await withAuthHeaders();
    const sid = (headers["Authorization"] || "").replace(/^Bearer\s+/i, "");
    const userId = sid ? await verifySession(sid) : null;
    if (!userId) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

    await prisma.conversation.delete({ where: { id, userId } });
    
    return NextResponse.json({ success: true, id });
  } catch (e: any) {
    return NextResponse.json({ error: e?.message ?? "Internal Server Error" }, { status: 500 });
  }
}


