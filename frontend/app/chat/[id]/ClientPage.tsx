"use client";

import { type ComponentType, useEffect, useRef, useState } from "react";
import {
  Thread,
  useThread,
  ThreadWelcome as AUIThreadWelcome,
  AssistantMessage as AUIAssistantMessage,
  UserMessage as AUIUserMessage,
  useAssistantRuntime,
  MessagePrimitive,
} from "@assistant-ui/react";
import { makeMarkdownText } from "@assistant-ui/react-markdown";
import { normalizeImageSrc } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ImageViewer } from "@/components/ui/image-viewer";
import { ChevronsDown } from "lucide-react";
import { PriceSnapshotTool } from "@/components/tools/price-snapshot/PriceSnapshotTool";
import { PurchaseStockTool } from "@/components/tools/purchase-stock/PurchaseStockTool";
import { ToolFallback } from "@/components/tools/ToolFallback";
import { updateDraftAndHistory, getRepo, saveRepo, getMessages } from "@/lib/chatHistory";
import { useThreadRuntime } from "@assistant-ui/react";
import { createPortal } from "react-dom";
import CustomComposer from "@/components/layout/CustomComposer";
import FileBubble from "@/components/ui/file-bubble";
import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// 自定义图片组件，支持缩略图和点击查看大图
const CustomImage = ({ src, alt }: { src: string; alt?: string }) => {
  console.log('CustomImage rendered:', { src, alt });
  // 若是后端原图 /uploads/images/img_*.ext，则推导缩略图 /uploads/thumbnails/img_*_thumb.jpg
  let thumb: string | undefined = undefined;
  try {
    const url = new URL(src, typeof window !== 'undefined' ? window.location.origin : 'http://localhost:3000');
    const match = url.pathname.match(/\/uploads\/images\/(img_[a-z0-9]+)\.[a-z0-9]+$/i);
    if (match) {
      thumb = `${url.origin}/uploads/thumbnails/${match[1]}_thumb.jpg`;
    }
  } catch {}
  return <ImageViewer src={src} alt={alt} thumbnailUrl={thumb} />;
};


const MarkdownText = makeMarkdownText({
  className: "w-full max-w-full",
  style: { maxWidth: "100%", width: "100%" },
  components: {
    img: CustomImage,
  }
} as any);

// 独立的 Markdown 渲染器，用于历史消息（不依赖 MessagePrimitive 上下文）
// 配置与 @assistant-ui/react-markdown 的 defaultComponents 保持一致
const StandaloneMarkdown = ({ text }: { text: string }) => {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        h1: ({ node, className, ...props }: any) => (
          <h1 className={`aui-md-h1 ${className || ''}`} {...props} />
        ),
        h2: ({ node, className, ...props }: any) => (
          <h2 className={`aui-md-h2 ${className || ''}`} {...props} />
        ),
        h3: ({ node, className, ...props }: any) => (
          <h3 className={`aui-md-h3 ${className || ''}`} {...props} />
        ),
        h4: ({ node, className, ...props }: any) => (
          <h4 className={`aui-md-h4 ${className || ''}`} {...props} />
        ),
        h5: ({ node, className, ...props }: any) => (
          <h5 className={`aui-md-h5 ${className || ''}`} {...props} />
        ),
        h6: ({ node, className, ...props }: any) => (
          <h6 className={`aui-md-h6 ${className || ''}`} {...props} />
        ),
        p: ({ node, className, ...props }: any) => (
          <p className={`aui-md-p ${className || ''}`} {...props} />
        ),
        a: ({ node, className, ...props }: any) => (
          <a className={`aui-md-a ${className || ''}`} {...props} />
        ),
        blockquote: ({ node, className, ...props }: any) => (
          <blockquote className={`aui-md-blockquote ${className || ''}`} {...props} />
        ),
        ul: ({ node, className, ...props }: any) => (
          <ul className={`aui-md-ul ${className || ''}`} {...props} />
        ),
        ol: ({ node, className, ...props }: any) => (
          <ol className={`aui-md-ol ${className || ''}`} {...props} />
        ),
        hr: ({ node, className, ...props }: any) => (
          <hr className={`aui-md-hr ${className || ''}`} {...props} />
        ),
        table: ({ node, className, ...props }: any) => (
          <table className={`aui-md-table ${className || ''}`} {...props} />
        ),
        th: ({ node, className, ...props }: any) => (
          <th className={`aui-md-th ${className || ''}`} {...props} />
        ),
        td: ({ node, className, ...props }: any) => (
          <td className={`aui-md-td ${className || ''}`} {...props} />
        ),
        tr: ({ node, className, ...props }: any) => (
          <tr className={`aui-md-tr ${className || ''}`} {...props} />
        ),
        sup: ({ node, className, ...props }: any) => (
          <sup className={`aui-md-sup ${className || ''}`} {...props} />
        ),
        pre: ({ node, className, ...props }: any) => (
          <pre className={`aui-md-pre ${className || ''}`} {...props} />
        ),
        code: ({ node, inline, className, ...props }: any) => (
          <code className={`${!inline ? '' : 'aui-md-inline-code'} ${className || ''}`} {...props} />
        ),
        img: ({ src, alt }: any) => {
          const normalizedSrc = normalizeImageSrc(src);
          if (!normalizedSrc) return null;
          return <CustomImage src={normalizedSrc} alt={alt} />;
        },
      }}
    >
      {text}
    </ReactMarkdown>
  );
};

// 使用共享的 normalizeImageSrc（带 :3001 端口逻辑）

// 安全提取图片 URL（仅在拿到字符串时返回，避免将对象 toString 成 "[object Object]")
function extractImageUrl(input: any): string | undefined {
  try {
    if (!input) return undefined;
    if (typeof input === "string") return input;

    // 常见平铺字段
    if (typeof input?.url === "string") return input.url;
    if (typeof input?.thumb_url === "string") return input.thumb_url;

    // image 结构
    if (typeof input?.image === "string") return input.image;
    if (typeof input?.image?.url === "string") return input.image.url;
    if (typeof input?.image?.thumb_url === "string") return input.image.thumb_url;

    // image_url 结构
    if (typeof input?.image_url === "string") return input.image_url;
    if (typeof input?.image_url?.url === "string") return input.image_url.url;
    if (typeof input?.image_url?.thumb_url === "string") return input.image_url.thumb_url;
    if (typeof input?.image_url?.url?.url === "string") return input.image_url.url.url;

    return undefined;
  } catch {
    return undefined;
  }
}

// -------- 历史消息回灌：统一归一与稳健渲染辅助 --------
const IMAGE_EXT = ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg', '.avif'];

function isImageByExt(url?: string) {
  if (!url) return false;
  try {
    const u = new URL(url, typeof window !== 'undefined' ? window.location.origin : 'http://local/');
    const pathname = u.pathname.toLowerCase();
    return IMAGE_EXT.some((ext) => pathname.endsWith(ext));
  } catch {
    const lower = String(url).toLowerCase();
    return IMAGE_EXT.some((ext) => lower.endsWith(ext));
  }
}

function isImageByMime(mime?: string) {
  return !!mime && mime.toLowerCase().startsWith('image/');
}

// 识别看起来像“文件直链”的 URL（用于去重：避免同一文件既出现在文件块，又以文本链接出现在文本气泡）
const FILE_EXT = ['.pdf','.doc','.docx','.xls','.xlsx','.csv','.zip','.rar','.7z','.tar','.gz','.ppt','.pptx','.pages'];
function isLikelyFileUrl(url?: string): boolean {
  if (!url) return false;
  try {
    const u = new URL(url, typeof window !== 'undefined' ? window.location.origin : 'http://local/');
    const pathname = u.pathname.toLowerCase();
    // 若是图片后缀则视为图片而不是文件
    if (IMAGE_EXT.some(ext => pathname.endsWith(ext))) return false;
    return FILE_EXT.some(ext => pathname.endsWith(ext))
      || /\/(files|pdf)\//i.test(pathname);
  } catch {
    const lower = String(url).toLowerCase();
    if (IMAGE_EXT.some(ext => lower.endsWith(ext))) return false;
    return FILE_EXT.some(ext => lower.endsWith(ext))
      || /\/(files|pdf)\//i.test(lower);
  }
}

type NormalizedParts = {
  text: string;
  images: string[];
  files: Array<{ url: string; name?: string; mime?: string; size?: number }>;
};

function normalizeContentParts(raw: any): NormalizedParts {
  const out: NormalizedParts = { text: '', images: [], files: [] };
  const arr = Array.isArray(raw) ? raw : [raw];

  const pushText = (t?: string) => {
    if (!t) return;
    const s = String(t).trim();
    if (!s) return;
    out.text = out.text ? `${out.text}\n${s}` : s;
  };

  for (const part of arr) {
    if (typeof part === 'string') { pushText(part); continue; }
    if (!part || typeof part !== 'object') continue;

    const lowerType = typeof part.type === 'string' ? String(part.type).toLowerCase() : '';
    const lowerKind = typeof part.kind === 'string' ? String(part.kind).toLowerCase() : '';

    // 顶层/常见结构：content 为字符串或对象(text)
    if (typeof (part as any).content === 'string') {
      pushText((part as any).content);
      // 不 return，继续以防同一 part 还包含图片/文件等字段
    } else if ((part as any).content && typeof (part as any).content?.text === 'string') {
      pushText((part as any).content.text);
    }

    // 文本形态（若只是一个指向文件的 Markdown 链接，则跳过，避免与文件块重复）
    if (typeof part.text === 'string') {
      const t = part.text as string;
      const m = t.match(/\[[^\]]+\]\((https?:[^\)]+)\)/);
      const linkUrl = m?.[1];
      if (linkUrl && isLikelyFileUrl(linkUrl)) {
        // 跳过：该文本只是文件链接，占用文件块呈现
      } else {
        pushText(t);
      }
      continue;
    }
    if (lowerType === 'text' || lowerType === 'input_text' || lowerKind === 'text') {
      if (typeof (part as any).value === 'string') pushText((part as any).value);
      else if (typeof (part as any).text === 'string') pushText((part as any).text);
      continue;
    }

    // 图片形态（大小写/多结构兼容）
    const imageUrl =
      (part as any).image_url || (part as any).imageUrl ||
      (typeof (part as any).image === 'string' ? (part as any).image : (part as any).image?.url) ||
      ((lowerType === 'image' || lowerType === 'input_image') ? ((part as any).url || (part as any).src) : undefined);
    if (typeof imageUrl === 'string') { out.images.push(imageUrl); continue; }

    // 文件/文档
    const isFileLike = ['file', 'document', 'attachment'].includes(lowerType) || ['file', 'document', 'attachment'].includes(lowerKind) || (part as any).File || (part as any).Document;
    const url = (part as any).url || (part as any).href || (part as any).link;
    const name = (part as any).name || (part as any).filename || (part as any).title;
    const mime = (part as any).mime || (part as any).mimetype || (part as any).contentType;
    const size = (part as any).size;
    if (isFileLike || url) {
      if (isImageByMime(mime) || isImageByExt(url)) { if (url) out.images.push(url); }
      else if (url) {
        out.files.push({ url, name, mime, size });
        // 若该 part 也混有文本字段，为避免“文本气泡重复显示文件链接”，不将其文本加入
      }
      continue;
    }

    // 嵌套富文本
    if (Array.isArray((part as any).content)) {
      const nested = normalizeContentParts((part as any).content);
      if (nested.text) pushText(nested.text);
      out.images.push(...nested.images);
      out.files.push(...nested.files);
    }
  }

  // 去重
  out.images = Array.from(new Set(out.images));
  const seen = new Set<string>();
  out.files = out.files.filter((f) => {
    if (!f.url) return false;
    if (seen.has(f.url)) return false;
    seen.add(f.url);
    return true;
  });

  return out;
}

// 将附件图片置于文本气泡上方（用于显示用户侧已选图片）
const CustomAttachment = ({ attachment }: { attachment: any }) => {
  try {
    if (attachment?.type === "image") {
      const raw =
        (attachment as any)?.url ||
        (attachment?.content?.find((c: any) => c?.type === "image")?.image ?? undefined);
      const src = normalizeImageSrc(
        typeof raw === "string" ? raw : raw?.url || raw?.thumb_url,
      );
      if (src) {
        return (
          <div className="mb-2">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={src}
              alt={attachment?.name || "Image"}
              className="rounded-lg border border-border cursor-pointer hover:opacity-80 transition-opacity"
              style={{
                minWidth: "250px",
                minHeight: "150px",
                maxWidth: "400px",
                maxHeight: "300px",
                width: "auto",
                height: "auto",
                objectFit: "contain",
              }}
              onClick={() => window.open(src, "_blank")}
            />
          </div>
        );
      }
    }
  } catch {}
  return (
    <div className="mb-2 p-2 border rounded bg-muted text-sm text-muted-foreground">
      📎 {attachment?.name || "Attachment"}
    </div>
  );
};

// 内容中的图片渲染器：assistant-ui 会直接把图片内容部分的字段铺到 props 上
function ContentImage(props: any) {
  const [ok, setOk] = useState(true);
  try {
    // 仅在拿到字符串时才参与渲染，避免 "[object Object]" 请求
    const raw = extractImageUrl(props);
    const src = raw ? normalizeImageSrc(raw) : undefined;
    try { console.log('[ContentImage] src ->', src, 'props:', props); } catch {}
    if (ok && src) {
      return (
        <div className="mb-2 w-full flex justify-end" style={{ order: 1 }}>
          <ImageViewer src={src} alt={typeof props?.alt === "string" ? props.alt : "Image"} />
        </div>
      );
    }
    if (src) {
      return (
        <a
          href={src}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 rounded border px-2 py-1 text-xs text-muted-foreground hover:text-foreground underline"
          style={{ order: 1 }}
        >
          查看图片
        </a>
      );
    }
  } catch {}
  return null;
}

// PDF 气泡渲染器
function ContentFile(props: any) {
  try {
    const url = typeof props?.url === 'string' ? props.url : undefined;
    const name = typeof props?.name === 'string' ? props.name : 'document';
    if (!url) return null;
    return (
      <div className="mb-2 w-full flex justify-end" style={{ order: 1 }}>
        <FileBubble url={url} name={name} mime={props?.mime || props?.contentType} size={props?.size} alignRight />
      </div>
    );
  } catch { return null; }
}

// 用户文本气泡：将 Markdown 文本包在右对齐的气泡中
function UserText(props: any) {
  try {
    const rawText = typeof (props as any)?.text === 'string' ? (props as any).text : (typeof (props as any)?.children === 'string' ? (props as any).children : '');
    const linkMatch = (rawText || '').match(/\[([^\]]+)\]\(([^\)]+)\)/);
    if (linkMatch) {
      const linkName = linkMatch[1];
      const linkUrl = linkMatch[2];
      const lower = (linkName || linkUrl || '').toLowerCase();
      const isCsv = /\.csv(\?.*)?$/.test(lower);
      const isXls = /\.(xlsx|xls)(\?.*)?$/.test(lower);

      if (isCsv) {
        // 轻量 CSV 3 行预览（后续会用 papaparse/xlsx 替换）
        const CsvPreview = () => {
          const [preview, setPreview] = useState<{ rows: any[]; columns: any[] } | null>(null);
          useEffect(() => {
            (async () => {
              try {
                const resp = await fetch(linkUrl);
                const text = await resp.text();
                const lines = text.split(/\r?\n/).filter(Boolean).slice(0, 4);
                const header = (lines[0] || '').split(',').slice(0, 10);
                const rows = lines.slice(1, 4).map(l => l.split(',').slice(0, header.length));
                setPreview({ columns: header, rows });
              } catch {}
            })();
          }, []);
          return (
            <div className="mb-2 w-full flex justify-end">
              <FileBubble url={linkUrl} name={linkName} mime={"text/csv"} preview={preview || undefined} alignRight />
            </div>
          );
        };
        return <CsvPreview />;
      }

      if (isXls) {
        return (
          <div className="mb-2 w-full flex justify-end">
            <FileBubble url={linkUrl} name={linkName} mime={"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"} alignRight />
          </div>
        );
      }

      // 其他类型统一气泡
      return (
        <div className="mb-2 w-full flex justify-end">
          <FileBubble url={linkUrl} name={linkName} mime={props?.mime || props?.contentType} alignRight />
        </div>
      );
    }

    const bubbleCls = "inline-block max-w-[80%] rounded-lg border border-border bg-gray-100 text-gray-900 dark:bg-gray-200 px-4 py-2 whitespace-pre-wrap";
    return (
      <div className="w-full flex justify-end" style={{ order: 2 }}>
        <div className={bubbleCls}><MarkdownText {...props} /></div>
      </div>
    );
  } catch { return null; }
}

// 自定义的用户消息：图片附件在上，文本内容在下
function CustomUserMessage() {
  return (
    <MessagePrimitive.Root className="w-full">
      {/* 统一右对齐：容器占满并将内容靠右 */}
      <div className="flex flex-col gap-1 w-full items-end">
        <MessagePrimitive.Content
          components={{ Image: ContentImage as any, Text: UserText as any, File: ContentFile as any, Document: ContentFile as any } as any}
        />
      </div>
    </MessagePrimitive.Root>
  );
}

function ContentDisclaimer() {
  return (
    <div className="mt-1 mb-3 px-4 text-center text-[11px] text-muted-foreground/80 select-none">
      我也可能会犯错，请核查重要信息
    </div>
  );
}

export default function ClientPage({ params, initialHasHistory, initialMessages = [] }: { params: { id: string }; initialHasHistory: boolean; initialMessages?: any[]; }) {
  const [isChatting, setIsChatting] = useState(false);
  const endRef = useRef<HTMLDivElement | null>(null);
  const [isNearBottom, setIsNearBottom] = useState(true);
  const chatContainerRef = useRef<HTMLElement | null>(null);
  const composerRef = useRef<HTMLDivElement | null>(null);
  const [composerHost, setComposerHost] = useState<HTMLElement | null>(null);
  const [centerHost, setCenterHost] = useState<HTMLElement | null>(null);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [scrollContainer, setScrollContainer] = useState<HTMLElement | null>(null);
  const BUFFER_PX = 24;
  const [preloadedMessages, setPreloadedMessages] = useState<any[]>(initialMessages || []);
  const initialPendingMessageRef = useRef<string | null>(null);
  const hasSentInitialRef = useRef(false);

  const getComposerHeight = () => {
    try {
      const raw = getComputedStyle(document.documentElement).getPropertyValue("--composer-h");
      const n = parseInt((raw || "").trim() || "0", 10);
      return Number.isFinite(n) && n > 0 ? n : 96;
    } catch {
      return 96;
    }
  };

  const scrollToBottomWithOffset = (behavior: ScrollBehavior = "smooth") => {
    try {
      const container = chatContainerRef.current;
      if (!container) return;
      const offset = getComposerHeight() + BUFFER_PX;
      const targetTop = container.scrollHeight - container.clientHeight - offset;
      container.scrollTo({ top: Math.max(targetTop, 0), behavior });
    } catch {}
  };

  // 监听消息长度变化，控制isChatting状态
  const messages = useThread((t) => t.messages);
  useEffect(() => {
    setIsChatting((messages as any[])?.length > 0);
  }, [messages]);

  // 恢复观察者包装器，确保props正确传递
  const withObserver = (Component: any) => {
    const Wrapped = (props: any) => <Component {...props} />;
    Wrapped.displayName = Component.displayName || Component.name || "Observed";
    return Wrapped;
  };

  const ObservedThreadWelcome = withObserver(AUIThreadWelcome);
  const ObservedAssistantMessage = withObserver(AUIAssistantMessage);
  const ObservedUserMessage = withObserver(AUIUserMessage);

  // 强制 Thread 在会话切换时重建
  const { id } = params;

  // URL 参数：欢迎态传递的消息（不立即发送）
  useEffect(() => {
    try {
      const urlParams = new URLSearchParams(window.location.search);
      const pendingMessage = urlParams.get('message');
      if (pendingMessage && pendingMessage.trim()) {
        initialPendingMessageRef.current = pendingMessage;
        window.history.replaceState({}, '', `/chat/${id}`);
      }
    } catch {}
  }, [id]);

  // 预加载历史消息（若SSR已提供则跳过首轮fetch，仅在缺失时请求）
  useEffect(() => {
    if ((initialMessages || []).length > 0) {
      // SSR 已注入，直接使用
      setPreloadedMessages(initialMessages);
      setIsChatting((initialMessages || []).length > 0);
      return;
    }
    (async () => {
      try {
        let msgs: any[] = [];
        try {
          const resp = await fetch(`/api/messages?conversationId=${id}`);
          if (resp.ok) {
            const data = await resp.json();
            msgs = Array.isArray(data?.items) ? data.items : [];
          }
        } catch {}
        if (msgs.length === 0) {
          const repo = getRepo(id);
          if (repo && Array.isArray(repo.messages)) {
            msgs = repo.messages.map(m => m.message);
          }
        }
        setPreloadedMessages(msgs);
        setIsChatting(msgs.length > 0);
      } catch {}
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // 导入与持久化
  const runtime = useThreadRuntime();
  useEffect(() => {
    try {
      if (!runtime) return;
      if (hasSentInitialRef.current) return;
      const pending = initialPendingMessageRef.current;
      if (!pending || !pending.trim()) return;
      const message = { id: `msg_${Date.now()}`, type: 'human', content: [{ type: 'text', text: pending }] } as any;
      (runtime as any).append?.(message);
      hasSentInitialRef.current = true;
    } catch {}
  }, [runtime]);
  useEffect(() => { try { updateDraftAndHistory(id, messages as any[]); if (runtime) saveRepo(id, runtime.export() as any); } catch {} }, [id, messages, runtime]);

  // 历史消息不使用 runtime.append() 导入，避免触发重复的 API 请求
  // 改为静态渲染 PreloadedMessages 组件

  // 绑定 portal 宿主
  useEffect(() => { try { const el = document.getElementById("composer-host"); if (el) setComposerHost(el); } catch {} }, []);
  useEffect(() => { try { const el = document.getElementById("composer-host-center"); if (el) setCenterHost(el); } catch {} }, []);

  // 滚动容器/底部哨兵
  useEffect(() => {
    try {
      const start = rootRef.current as HTMLElement | null; let node = start?.parentElement ?? null; let found: HTMLElement | null = null;
      while (node) { const style = window.getComputedStyle(node); if ((style.overflowY === "auto" || style.overflowY === "scroll")) { found = node as HTMLElement; break; } node = node.parentElement; }
      if (found) { chatContainerRef.current = found; setScrollContainer(found); }
    } catch {}
  }, []);
  useEffect(() => {
    try { if (!endRef.current) return; const observer = new IntersectionObserver((entries) => { const entry = entries[0]; setIsNearBottom(entry?.isIntersecting ?? true); }, { threshold: 0.01, root: scrollContainer as Element | null }); observer.observe(endRef.current); return () => observer.disconnect(); } catch {}
  }, [endRef, scrollContainer]);

  // 预加载静态渲染（有历史）
  function PreloadedMessages() {
    if (preloadedMessages.length === 0) return null;
    return (
      <div className="space-y-4">
        {preloadedMessages.map((msg, idx) => {
          const role = (msg?.role || '').toString().toLowerCase();
          const isUser = role === 'user' || role === 'human';
          const { text, images, files } = normalizeContentParts(msg?.content);
          const userBubbleCls = `inline-block max-w-[80%] rounded-lg border border-border bg-gray-100 text-gray-900 dark:bg-gray-200 px-4 py-2 whitespace-pre-wrap`;

          return (
            <div key={msg.id || idx} className="space-y-2">
              {images && images.length > 0 && images.map((u: string, i: number) => {
                const src = normalizeImageSrc(u);
                if (!src) return null;
                return (
                  <div key={`img-${i}`} className={`w-full flex ${isUser ? 'justify-end' : 'justify-start'}`}>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={src} alt={`image-${i}`} className="rounded-lg border border-border max-w-[400px] max-h-[300px] object-contain" />
                  </div>
                );
              })}
              {files && files.length > 0 && files.map((f, i) => (
                <div key={`file-${i}`} className={`w-full flex ${isUser ? 'justify-end' : 'justify-start'}`}>
                  <FileBubble url={f.url} name={f.name || 'document'} mime={f.mime} size={(f as any).size} alignRight={isUser} />
                </div>
              ))}
              {text && text.trim() && (
                isUser ? (
                  <div className={`w-full flex justify-end`}>
                    <div className={userBubbleCls}>
                      <StandaloneMarkdown text={text} />
                    </div>
                  </div>
                ) : (
                  <div className={`w-full flex justify-start`}>
                    <div className={`prose prose-sm md:prose-base dark:prose-invert leading-7 max-w-none`}>
                      <StandaloneMarkdown text={text} />
                    </div>
                  </div>
                )
              )}
            </div>
          );
        })}
      </div>
    );
  }

  if (preloadedMessages.length > 0) {
    return (
      <div className="flex h-full flex-col" ref={rootRef}>
        <div className="flex-1 min-h-0 overflow-y-auto">
          <div className="w-full h-full px-6 md:px-10 lg:px-14 mx-auto" style={{ paddingBottom: "var(--composer-h, 96px)", maxWidth: "calc((var(--chat-max-w) + 2 * 3.5rem) * 6/7)" }}>
            <div className="py-8"><PreloadedMessages /></div>
            <Thread
              key={id}
              welcome={{ message: null, suggestions: [] }}
              assistantMessage={{ components: { Text: MarkdownText, ToolFallback } }}
              tools={[PriceSnapshotTool, PurchaseStockTool]}
              components={{ 
                Composer: () => null, 
                ThreadWelcome: () => null, 
                AssistantMessage: ObservedAssistantMessage, 
                UserMessage: CustomUserMessage 
              }}
            />
            <div ref={endRef} aria-hidden className="h-1" />
          </div>
        </div>
        {composerHost && createPortal(<><CustomComposer /><ContentDisclaimer /></>, composerHost)}
      </div>
    );
  }

  // 欢迎态只在确认为“无历史”时呈现
  const isEmpty = ((messages as any[])?.length || 0) === 0;
  if (!initialHasHistory && !isChatting && isEmpty) {
    return (
      <div className="flex flex-1 flex-col" ref={rootRef}>
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
    <div className="flex h-full flex-col" ref={rootRef}>
      <div className="flex-1 min-h-0">
        <div className="w-full h-full px-6 md:px-10 lg:px-14 mx-auto" style={{ paddingBottom: "var(--composer-h, 96px)", maxWidth: "calc((var(--chat-max-w) + 2 * 3.5rem) * 6/7)" }}>
          <Thread
            key={id}
            welcome={{ message: null, suggestions: [] }}
            assistantMessage={{ components: { Text: MarkdownText, ToolFallback } }}
            tools={[PriceSnapshotTool, PurchaseStockTool]}
            components={{ 
              Composer: () => null, 
              ThreadWelcome: () => null, 
              AssistantMessage: ObservedAssistantMessage, 
              UserMessage: CustomUserMessage 
            }}
          />
          <div ref={endRef} aria-hidden className="h-1" />
        </div>
      </div>
      {composerHost && createPortal(<><CustomComposer /><ContentDisclaimer /></>, composerHost)}
      {!isNearBottom && (
        <div className="fixed right-6 bottom-24">
          <Button type="button" onClick={() => scrollToBottomWithOffset()} className="rounded-full shadow-md pl-3 pr-3 h-10" aria-label="回到最新">
            <ChevronsDown className="h-5 w-5 mr-2" /> 回到最新
          </Button>
        </div>
      )}
    </div>
  );
}


