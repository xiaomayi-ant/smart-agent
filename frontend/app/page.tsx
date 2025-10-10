
"use client";

import { useEffect, useRef, useState, type ComponentType } from "react";
import { createPortal } from "react-dom";
import { Thread, useThread, ThreadWelcome as AUIThreadWelcome, AssistantMessage as AUIAssistantMessage, UserMessage as AUIUserMessage } from "@assistant-ui/react";
import { MyRuntimeProvider } from "./MyRuntimeProvider";
import { PriceSnapshotTool } from "@/components/tools/price-snapshot/PriceSnapshotTool";
import { PurchaseStockTool } from "@/components/tools/purchase-stock/PurchaseStockTool";
import { ToolFallback } from "@/components/tools/ToolFallback";
import { makeMarkdownText } from "@assistant-ui/react-markdown";
import CustomComposer from "@/components/layout/CustomComposer";
import { useChatUI } from "@/lib/chatUiContext";
import { ImageViewer } from "@/components/ui/image-viewer";

// 自定义图片组件，支持缩略图和点击查看大图
const CustomImage = ({ src, alt }: { src: string; alt?: string }) => {
  console.log('CustomImage rendered:', { src, alt });
  // 检查是否是我们的缩略图格式 (data URL)
  const isDataUrl = src.startsWith('data:');
  return <ImageViewer src={src} alt={alt} thumbnailUrl={isDataUrl ? src : undefined} />;
};


const MarkdownText = makeMarkdownText({
  components: {
    img: CustomImage,
  }
});

// 欢迎文案将放入 ThreadWelcome 的配置中

function ContentDisclaimer() {
  return (
    <div className="mt-1 mb-3 px-4 text-center text-[11px] text-muted-foreground/80 select-none">
      我也可能会犯错，请核查重要信息
    </div>
  );
}

function HomeInner() {
  const { isChatting, setIsChatting, hasHomeReset } = useChatUI();
  const endRef = useRef<HTMLDivElement | null>(null);
  const [isNearBottom, setIsNearBottom] = useState(true);
  const chatContainerRef = useRef<HTMLDivElement | null>(null);
  const composerRef = useRef<HTMLDivElement | null>(null);
  const [composerHost, setComposerHost] = useState<HTMLElement | null>(null);
  const [centerHost, setCenterHost] = useState<HTMLElement | null>(null);
  const [listenerReadyAt, setListenerReadyAt] = useState<number | null>(null);
  const [eventReceived, setEventReceived] = useState(false);
  const BUFFER_PX = 24;

  // 首页挂载日志
  useEffect(() => {
    try { console.log('[HOME] mount', { href: typeof window !== 'undefined' ? window.location.href : 'ssr' }); } catch {}
  }, []);

  // 同页两态：不再在首页监听并跳转到 /chat/[id]



  // 包装指定组件，注入观察逻辑
  const withObserver = <P extends Record<string, unknown>>(Comp: ComponentType<P>) => {
    return function ObservedComp(props: P) {
      const length = useThread((t) => t.messages.length);
      useEffect(() => {
        setIsChatting(length > 0);
      }, [length]);
      return <Comp {...(props as P)} />;
    };
  };

  const ObservedThreadWelcome = withObserver(AUIThreadWelcome as unknown as ComponentType<any>);
  const ObservedAssistantMessage = withObserver(AUIAssistantMessage as unknown as ComponentType<any>);
  const ObservedUserMessage = withObserver(AUIUserMessage as unknown as ComponentType<any>);

  // 观察底部哨兵，判断是否在底部
  useEffect(() => {
    try {
      if (!endRef.current) return;
      const observer = new IntersectionObserver(
        (entries) => {
          const entry = entries[0];
          setIsNearBottom(entry?.isIntersecting ?? true);
        },
        { threshold: 0.01 }
      );
      observer.observe(endRef.current);
      return () => observer.disconnect();
    } catch {}
  }, [endRef]);

  // 获取全局 CSS 变量中的 composer 高度
  const getComposerHeight = () => {
    try {
      const raw = getComputedStyle(document.documentElement).getPropertyValue("--composer-h");
      const n = parseInt((raw || "").trim() || "0", 10);
      return Number.isFinite(n) && n > 0 ? n : 96;
    } catch {
      return 96;
    }
  };

  // 当在底部且消息变化时自动滚到底
  const messages = useThread((t) => t.messages);
  useEffect(() => {
    try {
      console.log('[HOME] messages length change', {
        href: typeof window !== 'undefined' ? window.location.href : 'ssr',
        len: Array.isArray(messages) ? (messages as any[]).length : 'N/A',
      });
      if (!isNearBottom) return;
      const container = chatContainerRef.current;
      if (!container) return;
      const offset = getComposerHeight() + BUFFER_PX;
      const targetTop = container.scrollHeight - container.clientHeight - offset;
      container.scrollTo({ top: Math.max(targetTop, 0), behavior: "smooth" });
    } catch {}
  }, [messages, isNearBottom]);

  // 绑定 portal 宿主
  useEffect(() => {
    try {
      const el = document.getElementById("composer-host");
      if (el) {
        setComposerHost(el);
        try { console.log(`[HOME] composerHost ready at`, Date.now(), { href: window.location.href }); } catch {}
      }
    } catch {}
  }, []);

  // 绑定欢迎态中部宿主
  useEffect(() => {
    try {
      const el = document.getElementById("composer-host-center");
      if (el) setCenterHost(el);
    } catch {}
  }, []);

  // 方案C：去掉 DOM 事件监听，消息长度兜底仍保留

  // Guard：依赖首页 reset 完成 + 有消息 + 宿主就绪 才进入消息态；否则保持欢迎态
  const shouldEnterChat = (hasHomeReset && (Array.isArray(messages) && (messages as any[]).length > 0) && !!composerHost);
  try {
    console.log('[HOME] render guard', {
      href: typeof window !== 'undefined' ? window.location.href : 'ssr',
      len: Array.isArray(messages) ? (messages as any[]).length : 'N/A',
      composerHost: !!composerHost,
      shouldEnterChat,
      hasHomeReset,
      isChatting,
    });
  } catch {}

  if (!shouldEnterChat) {
    return (
      <div className="flex flex-1 flex-col">
        {/* 三行网格：上/中/下，第二行专给输入框，锚定在中线 */}
        <div className="grid flex-1 grid-rows-[1fr_auto_1fr]" style={{ transform: "translateY(calc(var(--topbar-h, 0px) / -2 - 5vh))" }}>
          {/* Row 1: 欢迎标题靠近中线之上，不挤压中线 */}
          <div className="w-full text-center px-6 md:px-10 lg:px-14 self-end mb-8">
            <div className="mx-auto max-w-2xl">
              <h1 className="text-xl md:text-2xl font-normal text-foreground">我们先从哪里开始呢？</h1>
            </div>
          </div>

          {/* Row 2: 输入框严格居中，宽度与底部 overlay 一致 */}
          <div className="w-full">
            <div className="mx-auto w-full px-6 md:px-10 lg:px-14" style={{ maxWidth: "calc((var(--chat-max-w) + 2 * 3.5rem) * 6/7)" }}>
              <CustomComposer />
            </div>
          </div>

          {/* Row 3: 空行填充，维持对称 */}
          <div />
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* 消息区：唯一滚动容器 */}
      <div className="flex-1 min-h-0">
        <div
          className="w-full flex-1 min-h-0 overflow-y-auto overscroll-contain px-6 md:px-10 lg:px-14 mx-auto"
          style={{ paddingBottom: "var(--composer-h, 96px)", maxWidth: "calc((var(--chat-max-w) + 2 * 3.5rem) * 6/7)" }}
          ref={chatContainerRef}
        >
          <Thread
            welcome={{ message: null, suggestions: [] }}
            assistantMessage={{ components: { Text: MarkdownText, ToolFallback } }}
            tools={[PriceSnapshotTool, PurchaseStockTool]}
            components={{
              Composer: () => null,
              ThreadWelcome: () => null,
              AssistantMessage: ObservedAssistantMessage,
              UserMessage: ObservedUserMessage,
            }}
          />
          {/* 底部哨兵 */}
          <div ref={endRef} aria-hidden className="h-1" />
        </div>
      </div>

      {/* 通过 Portal 注入上层短输入框容器 */}
      {composerHost && createPortal(
        <>
          <CustomComposer />
          <ContentDisclaimer />
        </>,
        composerHost
      )}
    </div>
  );
}

export default function Home() {
  return (
    <MyRuntimeProvider key="home">
      <HomeInner />
    </MyRuntimeProvider>
  );
}