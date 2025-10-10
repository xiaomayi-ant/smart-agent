import { prisma } from "@/lib/db";
import ClientPage from "./ClientPage";

export default async function ChatPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let hasHistory = false;
  let initialMessages: Array<{ id: string; role: string; content: any; createdAt: Date }> = [];
  // 新建会话直跳（带 new=1）时跳过首屏 DB 预取，加快渲染
  // 注意：这里在服务端无法直接读取 window.location.search
  // 采用保守策略：当没有历史记录时，本就无需预取
  try {
    const count = await prisma.message.count({ where: { conversationId: id } });
    hasHistory = count > 0;
    if (hasHistory) {
      initialMessages = await prisma.message.findMany({
        where: { conversationId: id },
        orderBy: { createdAt: "asc" },
        select: { id: true, role: true, content: true, createdAt: true },
      });
    }
  } catch {}
  try { console.log(`[SRV] chat initialHasHistory`, { id, hasHistory }); } catch {}
  return <ClientPage params={{ id }} initialHasHistory={hasHistory} initialMessages={initialMessages} />;
}


