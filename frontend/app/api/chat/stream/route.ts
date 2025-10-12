import { NextRequest } from "next/server";
import { prisma } from "@/lib/db";
import { withAuthHeaders } from "@/lib/withAuthHeaders";
import { verifySession } from "@/lib/jwt";
import { randomUUID } from "node:crypto";
import { shouldUseVision, prepareVisionMessage, extractText } from "@/lib/messageAnalyzer";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const fetchCache = "force-no-store";

type UnknownRecord = Record<string, any>;

function pickConversationIdFromBody(body: UnknownRecord): string | null {
  const id = typeof body?.conversationId === "string" ? body.conversationId : null;
  return id && id.length > 0 ? id : null;
}

function pickThreadIdFromBody(body: UnknownRecord): string | null {
  const id = typeof body?.threadId === "string" ? body.threadId : null;
  return id && id.length > 0 ? id : null;
}

function getLangGraphApiBase(): string {
  const base = process.env["LANGGRAPH_API_URL"];
  if (!base) throw new Error("LANGGRAPH_API_URL is not configured");
  // 统一在尾部补 /api；将 localhost 替换为 127.0.0.1 以降低 DNS/代理抖动
  try {
    const u = new URL(base);
    if (u.hostname === 'localhost') u.hostname = '127.0.0.1';
    const s = u.toString().replace(/\/$/, "");
    return s.endsWith("/api") ? s : `${s}/api`;
  } catch {
    const trimmed = base.replace(/\/$/, "");
    return trimmed.endsWith("/api") ? trimmed : `${trimmed}/api`;
  }
}

function getLangChainApiKey(): string | undefined {
  return process.env["LANGCHAIN_API_KEY"] || undefined;
}

// 从 messages 中找最后一个用户消息（尽量宽松）
function findLastUserMessage(messages: any[]): any | null {
  if (!Array.isArray(messages)) return null;
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    const role = (m?.role || m?.type || "").toString().toLowerCase();
    if (role === "user" || role === "human") return m;
  }
  return null;
}

function extractTextFromMessage(message: any): string | null {
  try {
    if (!message) return null;
    const content = message.content;
    if (typeof content === "string") return content;
    if (Array.isArray(content)) {
      const first = content.find((p) => typeof p?.text === "string")?.text;
      if (first) return String(first);
      return String(content.map((p) => p?.text || p?.content || "").join(" ").trim());
    }
    if (content && typeof content === "object") {
      if (typeof content.text === "string") return content.text;
      if (typeof content.content === "string") return content.content;
    }
  } catch {}
  return null;
}

export async function POST(req: NextRequest) {
  const t0 = Date.now();
  function logp(stage: string) {
    try { console.log(`[PERF chat/stream] ${stage} +${Date.now() - t0}ms`); } catch {}
  }
  logp('start');
  // 解析 body
  const body = (await req.json().catch(() => null)) as UnknownRecord | null;
  logp('parsed-body');
  if (!body) {
    return new Response(JSON.stringify({ error: "Invalid JSON body" }), { status: 400, headers: { "Content-Type": "application/json" } });
  }
  const conversationId = pickConversationIdFromBody(body);
  const threadId = pickThreadIdFromBody(body);
  const messages = Array.isArray(body?.messages) ? (body!.messages as any[]) : [];

  if (!conversationId) {
    return new Response(JSON.stringify({ error: "conversationId is required" }), { status: 400, headers: { "Content-Type": "application/json" } });
  }
  if (!threadId) {
    return new Response(JSON.stringify({ error: "threadId is required" }), { status: 400, headers: { "Content-Type": "application/json" } });
  }

  // 鉴权并确定当前用户
  const headers = await withAuthHeaders({ "Content-Type": "application/json" });
  const sid = (headers["Authorization"] || "").replace(/^Bearer\s+/i, "");
  const userId = sid ? await verifySession(sid) : null;
  if (!userId) {
    return new Response(JSON.stringify({ error: "Unauthorized" }), { status: 401, headers: { "Content-Type": "application/json" } });
  }
  logp('auth-ok');

  // 改为“先转发后写库”：用户消息入库与会话更新放到后台，不阻塞首字
  try {
    const lastUser = findLastUserMessage(messages);
    if (lastUser) {
      (async () => {
        try {
          const tMsg0 = Date.now();
          await prisma.message.create({
            data: {
              id: randomUUID(),
              conversationId,
              role: "USER",
              content: lastUser,
              userId,
            },
            select: { id: true },
          });
          logp(`persist-user +${Date.now() - tMsg0}ms`);
          try {
            const userText = extractTextFromMessage(lastUser);
            const conv = await prisma.conversation.findFirst({ where: { id: conversationId, userId }, select: { title: true } });
            const tConv0 = Date.now();
            await prisma.conversation.update({
              where: { id: conversationId, userId },
              data: {
                updatedAt: new Date(),
                ...(userText && (conv?.title === "新聊天" || !conv?.title) ? { title: userText.slice(0, 40) } : {}),
              },
            });
            logp(`update-conv +${Date.now() - tConv0}ms`);
          } catch {}
        } catch (e) {
          console.warn("[chat/stream] persist user/update conv failed:", e);
        }
      })();
    }
  } catch {}

  // Late Binding: 将 file_ref 替换为短时效签名 image_url（避免前端阻塞）
  async function expandFileRefs(msgs: any[]): Promise<any[]> {
    try {
      const base = req.nextUrl.origin;
      const authHeaders = await withAuthHeaders();
      const expandContent = async (parts: any[]) => {
        const out: any[] = [];
        for (const p of parts) {
          if (p && p.type === 'file_ref' && p.file_id) {
            try {
              const resp = await fetch(`${base}/api/files/${encodeURIComponent(String(p.file_id))}` as any, { headers: authHeaders as any });
              if (resp.ok) {
                const data = await resp.json().catch(() => ({} as any));
                const url = typeof data?.url === 'string' ? data.url : undefined;
                if (url) { out.push({ type: 'image_url', image_url: { url, detail: 'low' } }); continue; }
              }
            } catch {}
          }
          out.push(p);
        }
        return out;
      };
      const expanded: any[] = [];
      for (const m of msgs) {
        const mm = { ...(m || {}) };
        const c = mm.content;
        if (Array.isArray(c)) {
          mm.content = await expandContent(c);
        }
        expanded.push(mm);
      }
      return expanded;
    } catch {
      return msgs;
    }
  }

  // 调用 LangGraph 流式接口
  const upstreamUrl = `${getLangGraphApiBase()}/threads/${encodeURIComponent(threadId)}/runs/stream`;
  const apiHeaders = await withAuthHeaders({ "Content-Type": "application/json" });
  const apiKey = getLangChainApiKey();
  if (apiKey) apiHeaders["x-api-key"] = apiKey;

  // 根据消息是否包含图片，选择是否传递工具给后端；在入模前进行 Late Binding
  let payloadMessages = await expandFileRefs(messages);
  let inputPayload: any = { messages: payloadMessages };
  try {
    if (shouldUseVision(payloadMessages as any)) {
      const lastUser = findLastUserMessage(payloadMessages);
      if (lastUser) {
        const vision = prepareVisionMessage(lastUser as any);
        // 与后端对齐：传递一个 tools 数组（示例结构，可按后端实际需要调整）
        inputPayload.tools = [
          {
            type: "vision_qa",
            name: "vision-qa",
            question: vision.question,
            images: vision.images,
          },
        ];
      }
    }
  } catch {}

  const tUp0 = Date.now();
  const upstream = await fetch(upstreamUrl, {
    method: "POST",
    headers: { ...apiHeaders, Connection: 'keep-alive' },
    body: JSON.stringify({ input: inputPayload }),
    // 将前端中止透传到上游，避免多余占用
    signal: (req as any).signal,
  });
  logp(`upstream-resp +${Date.now() - tUp0}ms`);

  if (!upstream.ok || !upstream.body) {
    return new Response(JSON.stringify({ error: `Upstream error ${upstream.status}` }), { status: 502, headers: { "Content-Type": "application/json" } });
  }

  // 准备转发 SSE，同时在服务端累积助手文本
  let assistantText = "";
  let buffer = "";
  const decoder = new TextDecoder();

  const stream = new ReadableStream<Uint8Array>({
    start: async (controller) => {
      const reader = upstream.body!.getReader();
      let firstBlockAt: number | null = null;
      let aborted = false;
      const onAbort = () => {
        aborted = true;
        try { reader.cancel(); } catch {}
        try { controller.close(); } catch {}
      };
      try { (req as any).signal?.addEventListener('abort', onAbort, { once: true } as any); } catch {}
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          if (value) {
            try { controller.enqueue(value); } catch {
              // 若控制器已关闭（例如前端中止），结束读取循环
              break;
            }
          }

          // 累积并解析 SSE 块，以便提取最终文本
          buffer += decoder.decode(value, { stream: true });
          let idx: number;
          while ((idx = buffer.indexOf("\n\n")) !== -1 || (idx = buffer.indexOf("\r\n\r\n")) !== -1) {
            const block = buffer.slice(0, idx);
            buffer = buffer.slice(idx + (buffer[idx] === "\r" ? 4 : 2));
            const lines = block.split(/\r?\n/);
            let event: string | null = null;
            const dataLines: string[] = [];
            for (const line of lines) {
              if (line.startsWith("event:")) event = line.slice(6).trim();
              else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
            }
            if (!event) continue;
            const dataStr = dataLines.join("\n");
            if (!dataStr) continue;
            try {
              const parsed = JSON.parse(dataStr);
              if (!firstBlockAt) { firstBlockAt = Date.now(); logp(`first-sse-block +${firstBlockAt - t0}ms`); }
              // 兼容多种事件格式，取到“最终文本”
              if (event === "partial_ai" && Array.isArray(parsed) && parsed[0]?.content) {
                // 假定 partial_ai 携带的是完整内容，直接覆盖
                assistantText = String(parsed[0].content ?? "");
              } else if (event === "message" && parsed?.choices?.[0]?.delta?.content) {
                assistantText += String(parsed.choices[0].delta.content);
              } else if (event === "on_chain_end" && parsed?.output) {
                const out = typeof parsed.output === "string" ? parsed.output : JSON.stringify(parsed.output);
                assistantText = out; // 认为该输出即最终内容
              }
            } catch {
              // ignore parse errors
            }
          }
        }
      } catch (e) {
        // 中止场景不视为错误；让流程继续到收尾阶段写库
        if (!aborted) {
          console.error("[chat/stream] upstream read error", e);
          try { controller.error(e as any); } catch {}
        }
        // 不 return，统一在后续收尾里处理入库
      } finally {
        try { reader.releaseLock(); } catch {}
        try { (req as any).signal?.removeEventListener('abort', onAbort as any); } catch {}
      }

      // 流结束：写入助手消息并更新会话时间与 threadId；若会话无标题则用首条用户消息生成默认标题
      try {
        // 只要有输出（不论长度/是否中止），就记录为一条完整助手消息
        if (assistantText && assistantText.trim().length > 0) {
          await prisma.message.create({
            data: {
              id: randomUUID(),
              conversationId,
              role: "ASSISTANT",
              content: { type: "text", text: assistantText, meta: { aborted } },
              userId,
            },
            select: { id: true },
          });
        }
        // 读取会话与首条用户消息；若标题仍为默认或为空，则用首条文本设为标题
        const [conv, firstUserInDb] = await Promise.all([
          prisma.conversation.findFirst({ where: { id: conversationId, userId }, select: { title: true } }),
          prisma.message.findFirst({
            where: { conversationId, role: "USER" },
            orderBy: { createdAt: "asc" },
            select: { content: true },
          }),
        ]);
        let newTitle: string | undefined;
        try {
          const t = extractTextFromMessage(firstUserInDb ? { content: (firstUserInDb as any).content } : null);
          if (t && t.trim().length > 0) newTitle = t.trim().slice(0, 40);
        } catch {}
        await prisma.conversation.update({
          where: { id: conversationId, userId },
          data: {
            updatedAt: new Date(),
            threadId,
            ...(newTitle && (conv?.title === "新聊天" || !conv?.title) ? { title: newTitle } : {}),
          },
        });
      } catch (e) {
        console.warn("[chat/stream] failed to persist assistant message/update conv:", e);
      }

      try { if (!aborted) controller.close(); } catch {}
      logp('stream-closed');
    },
  });

  const res = new Response(stream, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
  logp('response-created');
  return res;
}


