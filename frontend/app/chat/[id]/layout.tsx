"use client";

import { type ReactNode, use, useEffect, useState } from "react";
import { MyRuntimeProvider } from "../../MyRuntimeProvider";

export default function ChatRouteLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [threadId, setThreadId] = useState<string | null>(null);
  
  // 获取 threadId 用作 key
  useEffect(() => {
    try { console.log('[LAYOUT] chat mount', { id }); } catch {}
    (async () => {
      try {
        // 优先读取URL参数中的 tid（来自新建会话时的直传），避免额外请求
        const urlTid = (() => {
          try {
            const sp = new URLSearchParams(window.location.search);
            const t = sp.get('tid');
            return (t && t.trim()) ? t : null;
          } catch { return null; }
        })();

        if (urlTid) {
          setThreadId(urlTid);
          console.log(`[LAYOUT] use URL tid for key:`, urlTid);
        } else {
          const r = await fetch(`/api/conversations/${id}`);
          if (r.ok) {
            const info = await r.json();
            const tid = info?.threadId || null;
            setThreadId(tid);
            console.log(`[LAYOUT] Got threadId for key:`, tid);
          }
        }
      } catch {
        // 如果获取失败，使用 conversationId 作为 key
        setThreadId(id);
      }
    })();
    return () => {
      try { console.log('[LAYOUT] chat unmount', { id }); } catch {}
    };
  }, [id]);
  
  // 不再在 threadId 为空时整页 Loading，避免卸载/重建导致闪烁
  // 将 threadId 为空时临时回退为会话 id，Provider 内部已做稳定化处理
  const safeThreadId = threadId || id;

  // 使用 conversationId 作为 key，避免 threadId 变化导致 Provider 重新挂载
  return <MyRuntimeProvider key={id} conversationId={id} threadId={safeThreadId}>{children}</MyRuntimeProvider>;
}


