"use client";

import { useEffect, useRef, useState, useMemo, useCallback } from "react";
import { ChatUIContext } from "@/lib/chatUiContext";
import { AssistantRuntimeProvider, AttachmentAdapter, PendingAttachment, CompleteAttachment } from "@assistant-ui/react";
import { useLangGraphRuntime, LangChainMessage } from "@assistant-ui/react-langgraph";
import { createThread, sendMessage, visionStream, uploadAsync } from "@/lib/chatApi";
import { normalizeImageSrc as sharedNormalizeImageSrc } from "@/lib/utils";

// 定义本地附件状态接口
interface LocalAttachment {
  id: string;
  type: "file" | "image" | "document";
  name: string;
  contentType: string;
  size: number;
  file: File;
  fileId?: string;
  url?: string;  // 预览 URL（用于前端显示）
  signedUrl?: string;  // 🔑 签名 URL（用于发送给 AI）
  status: any; // 使用any来避免复杂的类型匹配
  createdAt: number;
  deleted?: boolean;
  fileContent?: string; // 新增：保存文件内容
}

export function MyRuntimeProvider({
  children,
  conversationId,
  threadId: propThreadId,
}: Readonly<{
  children: React.ReactNode;
  conversationId?: string;
  threadId?: string;
}>) {
  const runtimeIdRef = useRef<string>(`rt_${Math.random().toString(36).slice(2, 9)}`);
  const [attachments, setAttachments] = useState<LocalAttachment[]>([]); // 本地状态管理附件
  const attachmentsRef = useRef<LocalAttachment[]>([]); // 使用ref来保存最新状态
  const [isUploading, setIsUploading] = useState(false); // 添加上传状态标志
  const pendingUploadsRef = useRef<Set<string>>(new Set()); // 跟踪进行中的上传
  const isStreamingRef = useRef(false); // 内部标志（避免重复调用）
  const [isStreaming, setIsStreaming] = useState(false); // 对外可观察状态，用于UI三态
  const lastValidRuntimeRef = useRef<any>(null); // 保持最后一个有效的runtime
  const streamDoneRef = useRef<{ promise: Promise<void>; resolve: () => void } | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  
  // 调试：监控 isStreaming 状态变化
  useEffect(() => {
    console.log('[MyRuntimeProvider] isStreaming 状态变化为:', isStreaming);
  }, [isStreaming]);
  // 使用传入的 threadId，如果没有则异步获取
  const [threadId, setThreadId] = useState<string | undefined>(propThreadId);
  const threadIdRef = useRef<string | undefined>(propThreadId);
  
  useEffect(() => {
    if (propThreadId) {
      setThreadId(propThreadId);
      threadIdRef.current = propThreadId;
      console.log(`[RT] Using prop threadId:`, propThreadId);
      return;
    }
    
    // 如果有 conversationId，异步获取对应的 threadId
    if (conversationId) {
      (async () => {
        try {
          const r = await fetch(`/api/conversations/${conversationId}`);
          if (r.ok) {
            const info = await r.json();
            if (typeof info?.threadId === "string" && info.threadId) {
              setThreadId(info.threadId);
              console.log(`[RT] threadId(async)`, { runtimeId: runtimeIdRef.current, threadId: info.threadId });
            }
          }
        } catch {}
      })();
    } else {
      // 首页场景：没有 conversationId，生成临时 threadId
      const tempThreadId = `temp_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
      setThreadId(tempThreadId);
      threadIdRef.current = tempThreadId;
      console.log(`[RT] Generated temp threadId for home:`, tempThreadId);
    }
  }, [conversationId, propThreadId]);

  // 保持 threadId 引用稳定，供 adapter/stream 读取
  useEffect(() => { threadIdRef.current = threadId; }, [threadId]);

  // UI 状态：是否进入消息态（方案C：用上下文替代瞬时事件）
  const [uiIsChatting, setUiIsChatting] = useState(false);
  const [hasHomeReset, setHasHomeReset] = useState(false);

  // 规范化图片URL：相对路径 /uploads/... → http(s)://<host>:3001/uploads/...
  const normalizeImageSrc = (src?: string) => sharedNormalizeImageSrc(src);

  // 当进入首页（无 conversationId）时，确保重置为欢迎态
  useEffect(() => {
    try {
      if (!conversationId) {
        console.log(`[RT] reset uiIsChatting=false on home`, { runtimeId: runtimeIdRef.current });
        setUiIsChatting(false);
        setHasHomeReset(false);
      }
    } catch {}
  }, [conversationId]);

  // 首页：在 runtime 就绪后做一次 reset，清空旧消息，随后标记 hasHomeReset=true
  // 注意：依赖于下方声明的 runtime，因此将 effect 放在 runtime 声明之后

  // 状态追踪函数
  const logStateChange = (action: string, data: any) => {
    console.log(`[STATE] ${action}:`, data);
  };

  // 更新ref当attachments状态变化时
  const updateAttachmentsRef = (newAttachments: LocalAttachment[]) => {
    attachmentsRef.current = newAttachments;
    console.log(`[REF] 更新附件引用，当前数量: ${newAttachments.length}`);
  };

  const attachmentAdapter: AttachmentAdapter = useMemo<AttachmentAdapter>(() => ({
    accept: "*/*",

    // add 方法：预验证文件，生成 pending 元数据
    async add({ file }: { file: File }): Promise<PendingAttachment> {
      console.log(`[ADD] 开始添加文件: ${file.name}`);
      
      const maxSize = 10 * 1024 * 1024; // 10MB 上限
      if (file.size > maxSize) {
        throw new Error("文件大小超过 10MB");
      }
      
      const id = `file_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
      // 根据文件类型，赋予更语义化的附件类型，便于内置 UI 使用合适的样式/图标
      const attachmentType = file.type.startsWith("image/")
        ? "image"
        : (file.type === "application/pdf" ? "document" : "file");

      const attachment: PendingAttachment = {
        id,
        type: attachmentType as any,
        name: file.name,
        contentType: file.type,
        file,
        status: { type: "requires-action", reason: "composer-send" },
      };
      
      // 创建本地附件状态
      const localAttachment: LocalAttachment = {
        ...attachment,
        size: file.size,
        createdAt: Date.now(),
      };
      
      setAttachments((prev) => {
        const newState = [...prev, localAttachment];
        logStateChange("添加文件", { id, name: file.name, totalCount: newState.length });
        updateAttachmentsRef(newState); // 更新ref
        return newState;
      });
      
      console.log(`[ADD] 文件添加成功: ${file.name}, ID: ${id}`);
      // 预上传：图片/音频优先后台上传，缩短发送时等待
      try {
        if (attachmentType === 'image') {
          (async () => {
            try {
              const r = await uploadAsync(file, threadIdRef.current);
              setAttachments((prev) => {
                const newState = prev.map((a) => {
                  if (a.id !== id) return a;
                  return {
                    ...a,
                    fileId: r.fileId,
                    url: `/api/preview/image?fileId=${encodeURIComponent(r.fileId)}`,
                    signedUrl: r.signedUrl || r.url,
                    status: { type: 'complete' },
                  } as any;
                });
                updateAttachmentsRef(newState);
                return newState;
              });
            } catch (e) {
              // 失败不阻塞后续发送
              console.warn('[ADD] 预上传失败（忽略）', e);
            }
          })();
        }
      } catch {}

      return attachment;
    },

    // send 方法：只负责文件上传，不发送消息
    async send(attachment: PendingAttachment): Promise<CompleteAttachment> {
      console.log(`[SEND] 开始上传文件: ${attachment.name}`);
      
      // 设置上传状态
      setIsUploading(true);
      try { pendingUploadsRef.current.add(attachment.id); } catch {}
      
      // 确保threadId存在
      if (!threadIdRef.current) {
        console.log(`[SEND] 创建新线程`);
        const { thread_id } = await createThread();
        setThreadId(thread_id);
        threadIdRef.current = thread_id;
      }
      
      try {
        // 更新状态为 uploading，支持进度反馈
        setAttachments((prev) => {
          const newState = prev.map((a) => {
            if (a.id === attachment.id) {
              const updated = { ...a, status: { type: "uploading", progress: 0 } };
              logStateChange("开始上传", { id: a.id, name: a.name, progress: 0 });
              return updated;
            }
            return a;
          });
          updateAttachmentsRef(newState); // 更新ref
          return newState;
        });

        // 模拟进度更新
        const progressInterval = setInterval(() => {
          setAttachments((prev) => {
            const newState = prev.map((a) => {
              if (a.id === attachment.id && a.status.type === "uploading") {
                const newProgress = Math.min((a.status.progress || 0) + 25, 100);
                const updated = { ...a, status: { type: "uploading", progress: newProgress } };
                logStateChange("上传进度", { id: a.id, name: a.name, progress: newProgress });
                return updated;
              }
              return a;
            });
            updateAttachmentsRef(newState); // 更新ref
            return newState;
          });
        }, 300);

        let uploadResult: any;
        let completeAttachment: CompleteAttachment;
        let generatedSignedUrl: string | undefined = undefined;  // 🔑 保存签名 URL

        if (attachment.contentType.startsWith("image/")) {
          // 回退到原来的 OSS 模式：/api/upload?mode=async 上传 + /api/files/sign 获取可读直链
          console.log(`[SEND] 图片文件，上传到 OSS 并生成签名 URL（回到原模式）`);
          const formData = new FormData();
          formData.append("file", attachment.file);
          formData.append("threadId", threadIdRef.current || "");
          const response = await fetch("/api/upload?mode=async", { method: "POST", body: formData });
          if (!response.ok) throw new Error(`图片上传失败: ${response.statusText}`);
          uploadResult = await response.json();
          clearInterval(progressInterval);

          // 优先使用上传接口直接返回的 signedUrl；无则调用 /api/files/sign 获取短时效直链
          const signKey = uploadResult.key || (typeof uploadResult.url === 'string' ? uploadResult.url.split('.com/')[1] : '');
          let signedUrl = uploadResult.signedUrl || uploadResult.url;
          if (!uploadResult.signedUrl && signKey) {
            try {
              const signResponse = await fetch('/api/files/sign', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key: signKey, expiresSec: 3600 })
              });
              if (signResponse.ok) {
                const signData = await signResponse.json();
                signedUrl = signData.url;
                console.log(`[SEND] ✅ 签名 URL 生成成功，有效期: 1小时`);
              } else {
                console.warn(`[SEND] ⚠️  签名 URL 生成失败，使用原始 URL`);
              }
            } catch (e) {
              console.warn(`[SEND] ⚠️  签名 URL 请求异常，使用原始 URL`);
            }
          }

          generatedSignedUrl = signedUrl;

          // 构造包含完整图片元数据的 CompleteAttachment
          completeAttachment = {
            id: attachment.id,
            type: "image" as any,
            name: attachment.name,
            contentType: attachment.contentType,
            status: { type: "complete" },
            content: [{ type: "image", image: signedUrl }],
          } as any;

          // 额外添加 url 属性（用于前端预览，使用本地预览端点）
          (completeAttachment as any).url = `/api/preview/image?fileId=${encodeURIComponent(uploadResult.fileId)}`;
          (completeAttachment as any).signedUrl = signedUrl;

          console.log(`[SEND] 📋 双 URL 策略验证:`);
          console.log(`[SEND]   - 预览 URL: ${(completeAttachment as any).url}`);
          console.log(`[SEND]   - 签名 URL: ${(completeAttachment.content?.[0] as any)?.image?.substring(0, 80)}...`);
        } else if (attachment.contentType.startsWith("audio/")) {
          // 音频：直接作为文件占位，后续可上传并替换为可访问URL
          console.log(`[SEND] 音频文件，作为附件占位`);

          const formData = new FormData();
          formData.append("file", attachment.file);
          formData.append("threadId", threadIdRef.current || "");

          const response = await fetch("/api/upload?mode=async", {
            method: "POST",
            body: formData,
          });
          if (!response.ok) {
            throw new Error(`音频上传失败: ${response.statusText}`);
          }
          uploadResult = await response.json();
          clearInterval(progressInterval);

          completeAttachment = {
            id: attachment.id,
            type: "file" as any,
            name: attachment.name,
            contentType: attachment.contentType,
            status: { type: "complete" },
            content: [
              { type: "text", text: `🔉 音频：${attachment.name}` },
            ],
          };
        } else {
          // 非图片文件：统一走异步上传，确保拿到 fileId/url 以便本地回显 PDF 气泡
          console.log(`[SEND] 非图片文件，使用 /api/upload?mode=async 上传`);
          
          const formData = new FormData();
          formData.append("file", attachment.file);
          formData.append("threadId", threadIdRef.current || "");
          
          const response = await fetch("/api/upload?mode=async", {
            method: "POST",
            body: formData,
          });
          
          if (!response.ok) {
            throw new Error(`上传失败: ${response.statusText}`);
          }
          
          uploadResult = await response.json();
          clearInterval(progressInterval);
          
          console.log(`[SEND] 文件上传成功:`, uploadResult);

          // 返回一个文本内容块，渲染为可点击的链接（PDF 用预览端点，其他类型暂保留直链）
          completeAttachment = {
            id: attachment.id,
            type: attachment.contentType === "application/pdf" ? "document" : "file",
            name: attachment.name,
            contentType: attachment.contentType,
            status: { type: "complete" },
            content: [
              { type: "text", text: (
                attachment.contentType === "application/pdf"
                  ? `📄 [${attachment.name}](/api/preview/pdf?fileId=${encodeURIComponent(uploadResult.fileId)})`
                  : `📄 [${attachment.name}](${uploadResult.url})`
              ) },
            ],
          };
        }

        // 更新本地状态，保存文件内容和上传结果
          setAttachments((prev) => {
            const newState = prev.map((a) => {
              if (a.id === attachment.id) {
                const updated = {
                  ...a,
                  fileId: uploadResult.fileId,
                  // 本地状态中的可点击地址也切换为预览端点，避免直链在私有桶下失效
                  url: (a.contentType?.startsWith("image/")
                    ? `/api/preview/image?fileId=${encodeURIComponent(uploadResult.fileId)}`
                    : (a.contentType === "application/pdf"
                        ? `/api/preview/pdf?fileId=${encodeURIComponent(uploadResult.fileId)}`
                        : uploadResult.url
                      )
                  ),
                  // 🔑 保存签名 URL（用于发送给 AI）
                  signedUrl: a.contentType?.startsWith("image/") ? generatedSignedUrl : undefined,
                  status: { type: "complete" },
                  fileContent: attachment.contentType.startsWith("image/") ? "" : ""
                };
                // 🐛 调试日志
                console.log(`[SEND] 更新附件状态:`, {
                  id: updated.id,
                  name: updated.name,
                  isImage: updated.contentType?.startsWith("image/"),
                  fileId: updated.fileId,
                  hasSignedUrl: !!updated.signedUrl,
                  signedUrlLength: updated.signedUrl?.length
                });
                logStateChange("上传完成", { id: a.id, name: a.name, fileId: uploadResult.fileId });
                return updated;
              }
              return a;
            });
            updateAttachmentsRef(newState); // 更新ref
            return newState;
          });
        
        console.log(`[SEND] 文件上传完成: ${attachment.name}`);
        return completeAttachment;
      } catch (error: any) {
        console.error(`[SEND] 文件上传失败: ${attachment.name}`, error);
        
        setAttachments((prev) => {
          const newState = prev.map((a) => {
            if (a.id === attachment.id) {
              const updated = { ...a, status: { type: "requires-action", reason: error.message } };
              logStateChange("上传失败", { id: a.id, name: a.name, error: error.message });
              return updated;
            }
            return a;
          });
          updateAttachmentsRef(newState); // 更新ref
          return newState;
        });
        throw error;
      } finally {
        // 清除上传状态
        try { pendingUploadsRef.current.delete(attachment.id); } catch {}
        setIsUploading(false);
      }
    },

    // remove 方法：通知后端删除，更新状态，处理删除矛盾
    async remove(attachment: CompleteAttachment): Promise<void> {
      console.log(`[REMOVE] 开始删除文件: ${attachment.name}`);
      
      try {
        const localAttachment = attachmentsRef.current.find(a => a.id === attachment.id);
        const fileId = localAttachment?.fileId || attachment.id;
        const currentThreadId = threadIdRef.current || "";
        
        console.log(`[REMOVE] 删除参数:`, { fileId, threadId: currentThreadId, hasThreadId: !!currentThreadId });
        
        // 使用真实API删除文件
        const response = await fetch(`/api/files/${fileId}`, {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ threadId: currentThreadId }),
        });
        
        if (!response.ok) {
          console.warn(`[REMOVE] 删除文件API返回错误: ${response.status}`);
          // 不抛出错误，继续执行本地状态清理
        }
        
        // 直接更新本地状态，移除对不存在端点的调用
        setAttachments((prev) => {
          const newState = prev.filter((a) => a.id !== attachment.id);
          updateAttachmentsRef(newState);
          logStateChange("删除文件", { id: attachment.id, name: attachment.name, remainingCount: newState.length });
          return newState;
        });
        
        console.log(`[REMOVE] 文件删除完成: ${attachment.name}`);
      } catch (error) {
        console.error(`[REMOVE] 文件删除失败: ${attachment.name}`, error);
        
        // 即使删除失败，也要清理本地状态
        setAttachments((prev) => {
          const newState = prev.filter((a) => a.id !== attachment.id);
          updateAttachmentsRef(newState);
          return newState;
        });
        
        // 不抛出错误，避免界面崩溃
        console.log(`[REMOVE] 已清理本地状态，忽略删除错误`);
      }
    },
  }), []);

  // 移除 useThreadRuntime，我们将使用不同的方法
  
  // 使用稳定的threadId避免runtime重新创建导致的消息清空
  const stableThreadId = useMemo(() => {
    // 保守策略：在存在 conversationId 的会话页，仅使用 propThreadId/threadId；
    // 避免退化为 conversationId 伪造 threadId 造成多线程/分裂。
    if (propThreadId || threadId) return propThreadId || threadId;
    if (!conversationId) return `stable_${Date.now()}`; // 首页场景允许临时id
    return undefined; // 会话页但 threadId 未就绪时，交由下方逻辑等待
  }, [propThreadId, threadId, conversationId]);

  // 用 useCallback 固定 stream 引用
  const stream = useCallback(async (messages: LangChainMessage[], config: any) => {
      const STREAM_DEBUG = process.env.NEXT_PUBLIC_DEBUG_STREAM === "true";
      if (STREAM_DEBUG) {
        console.log(`[STREAM] stream() 被调用，消息数: ${messages.length}, 时间: ${new Date().toISOString()}`);
      }
      
      // 防止重复调用：返回一个等待主流结束后再完成的占位生成器
      if (isStreamingRef.current) {
        console.log(`[STREAM] 检测到重复调用，等待主流结束`);
        const waiter = streamDoneRef.current?.promise;
        return (async function* () {
          try {
            if (waiter) await waiter;
          } catch {}
          // 与主流完成时机对齐，立即宣告完成
          yield { event: "messages/complete", data: [] } as any;
        })();
      }
      
      isStreamingRef.current = true;
      // 设置流式状态，供 CustomComposer 显示中断按钮
      console.log('[MyRuntimeProvider] 设置 isStreaming = true');
      // 初始化主流完成的通知句柄
      try {
        let resolve!: () => void;
        const promise = new Promise<void>((r) => { resolve = r; });
        streamDoneRef.current = { promise, resolve };
      } catch {}
      setIsStreaming(true);
      console.log('[MyRuntimeProvider] setIsStreaming(true) 已调用');
      if (STREAM_DEBUG) {
        console.log(`[STREAM] 开始处理消息，消息数量: ${messages.length}`);
        console.log(`[STREAM] Using threadId:`, stableThreadId);
        try { console.log(`[STREAM] runtime pre-export len`, (lastValidRuntimeRef.current as any)?.export?.()?.messages?.length); } catch {}
      }
      
      // 首页场景：不再派发 DOM 事件，直接通过上下文切换 UI
      if (!conversationId) {
        try { setUiIsChatting(true); console.log(`[RT] uiIsChatting=true by stream start on home`); } catch {}
      }
      
      try {
        const t0 = performance.now?.() || Date.now();
        console.log(`[PERF front] stream-start`);
        // 移除乐观回显，交由 Assistant UI 自身处理，避免重复触发运行

        // 使用稳定的threadId，确保一致性
        // 确保发送前有真实 threadId（会话页必须等到 threadIdRef 有值或 URL 已提供）
        let currentThreadId = threadIdRef.current || stableThreadId;
        let waitLoops = 0;
        while (!currentThreadId && conversationId && waitLoops < 100) { // 最多等10秒
          await new Promise(r => setTimeout(r, 100));
          currentThreadId = threadIdRef.current || stableThreadId;
          waitLoops++;
        }
        if (!currentThreadId) {
          // 仅在首页（无 conversationId）允许创建新线程
          const { thread_id } = await createThread();
          currentThreadId = thread_id;
          console.log(`[RT] Created new threadId:`, currentThreadId);
          threadIdRef.current = currentThreadId;
        }

        // 仅等待图片就绪（soft timeout 3s），减少发送前阻塞
        try {
          console.log(`[TIMING] 🔍 检查图片附件状态(仅等待图片+3s软超时)...`);
          let loops = 0;
          const hasPendingImages = () => attachmentsRef.current.some(a => a?.contentType?.startsWith("image/") && (a?.status?.type ?? '') !== 'complete');
          const imagesCount = () => attachmentsRef.current.filter(a => a?.contentType?.startsWith("image/")).length;

          console.log(`[TIMING] 📎 图片附件数量: ${imagesCount()}`);
          console.log(`[TIMING] 📎 图片附件状态:`, attachmentsRef.current.filter(a => a?.contentType?.startsWith("image/")).map(a => ({
            name: a.name,
            status: a.status?.type,
            hasSignedUrl: !!(a as any).signedUrl,
          })));

          if (hasPendingImages()) {
            const waitStart = Date.now();
            while (hasPendingImages()) {
              await new Promise((r) => setTimeout(r, 100));
              loops++;
              if (loops % 10 === 0) {
                console.log(`[TIMING] ⏳ 等待图片就绪... ${loops * 100}ms`);
              }
              // 3s 软超时
              if (loops >= 30) {
                console.warn(`[TIMING] ⚠️ 图片等待超时(3s)，继续发送，后续在构建消息时按 fileId 交换直链/占位`);
                break;
              }
            }
            const waitTime = Date.now() - waitStart;
            console.log(`[TIMING] ✅ 图片等待结束，用时: ${waitTime}ms`);
          } else {
            console.log(`[TIMING] ✅ 无需等待图片`);
          }
        } catch (err) {
          console.error(`[TIMING] ❌ 图片等待检查异常:`, err);
        }

        // 处理 langchain/langgraph-sdk的流式响应转换为@assistant-ui/react-langgraph期望的格式
        const convertToLangGraphFormat = async function* (streamResponse: any) {
          try {
            console.log('[convertToLangGraphFormat] 生成器开始');
            let hasYieldedContent = false;
            let chunkCount = 0;
            let accumulatedContent = ""; // 累积Python后端的内容
            let currentMessageId = `msg_${Date.now()}`; // 当前消息ID
            let completedOnce = false; // 标记是否已完成
            if (STREAM_DEBUG) console.log(`[STREAM] 开始处理流式响应...`);
            
            for await (const chunk of streamResponse) {
              chunkCount++;
              if (STREAM_DEBUG) console.log(`[STREAM] 处理chunk ${chunkCount}:`, chunk);
              
              // 修改：处理新事件类型，并映射到前端期望的 'messages/partial' 和 'messages/complete'
              if (chunk && typeof chunk === 'object') {
                if (STREAM_DEBUG) console.log(`[STREAM] 处理事件类型: ${chunk.event}`);
                
                // 处理Python后端发送的partial_ai事件（与TypeScript后端一致）
                if (chunk.event === 'partial_ai' && chunk.data && Array.isArray(chunk.data)) {
                  hasYieldedContent = true;
                  
                  // 修改：Python后端发送的是完整内容，直接使用
                  if (chunk.data.length > 0 && chunk.data[0].content) {
                    // 使用后端发送的完整内容
                    accumulatedContent = chunk.data[0].content;
                    
                    // 统一使用当前流的消息ID，避免因为后端提供不同ID而造成跳动
                    const messageId = currentMessageId;
                    
                    // 确保消息ID一致，这样Assistant UI就能正确更新现有消息
                    const messagesWithId = [{
                      id: messageId,
                      type: 'ai',
                      content: accumulatedContent // 发送完整内容
                    }];
                    
                    if (STREAM_DEBUG) console.log(`[STREAM] 发送partial_ai事件，消息ID: ${messageId}, 内容长度: ${accumulatedContent.length}`);
                    yield { event: 'messages/partial', data: messagesWithId };
                  }
                } else if (chunk.event === 'tool_result' && chunk.data && Array.isArray(chunk.data)) {
                  // 映射 tool_result 到 messages/partial，并转换为 ai 类型
                  hasYieldedContent = true;
                  const toolMessages = chunk.data.map((msg: any, index: number) => {
                    if (msg.type === 'tool') {
                      // 将工具结果转换为AI消息
                      if (STREAM_DEBUG) console.log(`[STREAM] 转换工具消息为AI消息:`, msg);
                      return {
                        id: msg.id || `tool_${Date.now()}_${index}`,
                        type: 'ai',  // 转换为ai类型
                        content: msg.content
                      };
                    }
                    return {
                      ...msg,
                      id: msg.id || `tool_${Date.now()}_${index}`
                    };
                  });
                  yield { event: 'messages/partial', data: toolMessages };
                } else if (chunk.event === 'message' && chunk.data) {
                  // 处理OpenAI格式的聊天完成响应（兼容性）
                  const data = chunk.data;
                  if (data.choices && data.choices.length > 0) {
                    const choice = data.choices[0];
                    if (choice.delta && choice.delta.content) {
                      // 有内容更新，累积内容并发送完整内容
                      hasYieldedContent = true;
                      const deltaContent = choice.delta.content;
                      accumulatedContent += deltaContent;
                      yield { event: 'messages/partial', data: [{ 
                        id: currentMessageId,
                        type: 'ai', 
                        content: accumulatedContent  // 发送累积内容，不是增量内容
                      }] };
                    } else if (choice.finish_reason === 'stop') {
                      // 响应完成
                      yield { event: 'messages/complete', data: [] };
                    }
                  }
                } else if (chunk.event === 'error') {
                  // 显示上游错误为一条AI消息
                  hasYieldedContent = true;
                  const errData: any = chunk.data;
                  
                  // 提取简洁的错误消息，只显示一行文本
                  let msg = '未知错误';
                  if (typeof errData === 'string') {
                    msg = errData;
                  } else if (errData) {
                    // 优先提取 error 字段（可能是字符串或对象）
                    if (typeof errData.error === 'string') {
                      msg = errData.error;
                    } else if (errData.error?.message) {
                      msg = errData.error.message;
                    } else if (errData.message) {
                      msg = errData.message;
                    }
                  }
                  
                  // 指定与本次流一致的消息ID，更新同一条占位消息
                  yield { event: 'messages/partial', data: [{ 
                    id: currentMessageId,
                    type: 'ai', 
                    content: `处理请求时出错：${msg}`
                  }] };
                } else if (chunk.event === 'done') {
                  // 兼容 [DONE] 结束事件
                  yield { event: 'messages/complete', data: [] };
                  completedOnce = true;
                } else if (chunk.event === 'complete') {
                  // 映射 complete 到 messages/complete
                  yield { event: 'messages/complete', data: [] };
                  completedOnce = true;
                } else if (chunk.event === 'on_tool_end') {
                  // 处理工具执行完成事件
                  hasYieldedContent = true;
                  yield { event: 'messages/partial', data: [{ 
                    id: `tool_end_${Date.now()}`,
                    type: 'ai', 
                    content: chunk.data?.message || '工具执行完成'
                  }] };
                } else if (chunk.event === 'on_chain_end') {
                  // 处理链事件
                  if (STREAM_DEBUG) console.log(`[STREAM] 处理链事件:`, chunk);
                  if (chunk.data && chunk.data.output) {
                    hasYieldedContent = true;
                    yield { event: 'messages/partial', data: [{ 
                      id: `msg_${Date.now()}_tool`,
                      type: 'ai', 
                      content: typeof chunk.data.output === "string" ? chunk.data.output : JSON.stringify(chunk.data.output)
                    }] };
                  }
                } else if (chunk.event === 'approval_required') {
                  // 人工确认事件：弹窗确认并调用前端代理，随后本地插入结果
                  try {
                    const threadId = chunk?.data?.thread_id as string;
                    const calls = (chunk?.data?.tool_calls || []) as any[];
                    const first = Array.isArray(calls) && calls.length > 0 ? calls[0] : null;
                    const toolName = first?.name || first?.tool || first?.toolName || 'unknown_tool';
                    const args = first?.args || first?.arguments || {};
                    const toolCallId = first?.id || undefined;

                    const preview = `${toolName}\n${JSON.stringify(args, null, 2)}`;
                    const ok = typeof window !== 'undefined' ? window.confirm(`检测到需要人工确认的入库操作:\n\n${preview}\n\n是否确认执行？`) : false;

                    // 立即回显一条AI提示
                    yield { event: 'messages/partial', data: [{ 
                      id: `approval_${Date.now()}`,
                      type: 'ai',
                      content: ok ? '已确认，正在执行入库工具…' : '已拒绝执行该入库操作。'
                    }] };

                    // 调用前端代理，透传到后端审批接口
                    try {
                      const resp = await fetch('/api/tools/approval', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                          threadId: threadId,
                          toolName,
                          args,
                          approve: ok,
                          toolCallId,
                        })
                      });
                      const data = await resp.json().catch(() => ({} as any));
                      if (ok) {
                        // 确认后如有结果，继续本地回显结果摘要
                        const resultText = typeof data?.result === 'string' ? data.result : JSON.stringify(data?.result || {});
                        yield { event: 'messages/partial', data: [{ 
                          id: `approval_result_${Date.now()}`,
                          type: 'ai',
                          content: resultText && resultText !== '{}' ? `✅ 入库工具执行完成：\n${resultText}` : '✅ 入库工具执行完成。'
                        }] };
                      }
                    } catch (e) {
                      yield { event: 'messages/partial', data: [{ 
                        id: `approval_err_${Date.now()}`,
                        type: 'ai',
                        content: `审批处理失败，请稍后重试。`
                      }] };
                    }
                  } catch (e) {
                    if (STREAM_DEBUG) console.warn('[STREAM] 处理 approval_required 事件失败', e);
                  }
                } else if (chunk.event && chunk.data) {
                  // 其他事件，直接传递
                  yield chunk;
                } else {
                  if (STREAM_DEBUG) console.warn(`[STREAM] 未知chunk格式:`, chunk);
                }
              } else {
                if (STREAM_DEBUG) console.warn(`[STREAM] 无效chunk:`, chunk);
              }
            }
            
            if (STREAM_DEBUG) console.log(`[STREAM] 流式响应处理完成，总chunk数: ${chunkCount}, 是否有内容: ${hasYieldedContent}`);
            
            // 如果没有收到任何内容，发送一个默认响应
            if (!hasYieldedContent) {
              console.log(`[STREAM] 没有收到内容，发送默认响应`);
              // 指定与本次流一致的消息ID，更新同一条占位消息
              yield { event: 'messages/partial', data: [{ 
                id: currentMessageId,
                type: 'ai', 
                content: '正在处理您的请求...' 
              }] };
              yield { event: 'messages/complete', data: [] };
            }
          } catch (error) {
            console.error(`[STREAM] 流式响应处理错误:`, error);
            // 使用新的占位ID（与本次流唯一绑定），避免未定义变量导致的类型报错
            const errorMessageId = `msg_${Date.now()}_err`;
            yield { event: 'messages/partial', data: [{ id: errorMessageId, type: 'ai', content: '处理过程中出现错误，请重试。' }] };
            yield { event: 'messages/complete', data: [] };
          } finally {
            // 流完成后：触发附件清理，随后统一清理运行态
            try {
              setAttachments((prev) => {
                const newState = prev.filter(a => (a?.status?.type ?? '') !== 'complete');
                updateAttachmentsRef(newState);
                console.log(`[STREAM] complete: 清理已完成附件，剩余数量: ${newState.length}`);
                return newState;
              });
            } catch {}
            // 统一落地：结束运行态并通知所有等待者
            try { isStreamingRef.current = false; } catch {}
            try { setIsStreaming(false); } catch {}
            try { streamDoneRef.current?.resolve(); } catch {}
          }
        };

        // 检查是否有附件需要处理，包括图片和文档文件
        console.log(`[STREAM] 附件引用状态检查:`, {
          attachmentsRefLength: attachmentsRef.current?.length || 0,
          attachmentsRef: attachmentsRef.current
        });
        
        const completedAttachments = attachmentsRef.current.filter(a => a.status.type === "complete");
        
        console.log(`[STREAM] 当前附件状态:`, attachmentsRef.current.map(a => ({
          id: a.id,
          name: a.name,
          status: a.status.type,
          contentType: a.contentType,
          fileId: a.fileId,
          hasUrl: !!a.url,
          url: a.url
        })));
        
        console.log(`[STREAM] 过滤后的已完成附件数量: ${completedAttachments.length}`);
        
        if (completedAttachments.length > 0) {
          console.log(`[STREAM] 发现 ${completedAttachments.length} 个已完成的附件，构造多模态消息`);
          console.log(`[STREAM] 附件详情:`, completedAttachments.map(a => ({
            name: a.name,
            contentType: a.contentType,
            fileId: a.fileId,
            isImage: a.contentType?.startsWith("image/")
          })));
          
          // 构造附件内容块（支持表格预览/通用卡片）
          const buildFilePart = async (attachment: any) => {
            console.log(`[buildFilePart] 处理附件:`, {
              name: attachment.name,
              contentType: attachment.contentType,
              hasUrl: !!attachment.url,
              hasSignedUrl: !!attachment.signedUrl
            });
            
            try {
              if (attachment.contentType?.startsWith("image/")) {
                // 🚀 优先使用 signedUrl（OSS 签名 URL）；若缺失，尝试通过 fileId 获取一次签名直链
                let imageUrl = attachment.signedUrl;
                if (!imageUrl) {
                  const preview = String(attachment.url || "");
                  const m = preview.match(/[?&]fileId=([^&]+)/i);
                  const fileId = m?.[1] ? decodeURIComponent(m[1]) : undefined;
                  if (fileId) {
                    try {
                      const resp = await fetch(`/api/files/${encodeURIComponent(fileId)}`);
                      if (resp.ok) {
                        const data = await resp.json().catch(() => ({} as any));
                        if (typeof data?.url === 'string' && data.url.startsWith('http')) {
                          imageUrl = data.url;
                          console.log(`[buildFilePart] ✅ 通过 fileId 交换签名直链成功`);
                        }
                      }
                    } catch {}
                  }
                }
                // 仍然没有直链则避免把预览URL发给模型
                if (!imageUrl || !/^https?:\/\//i.test(imageUrl)) {
                  console.warn(`[buildFilePart] ❌ 无法获取可直达的图片 URL，改为文本占位`);
                  return { type: "text" as const, text: `[图片未就绪: ${attachment.name}]` };
                }
                
                console.log(`[buildFilePart] ✅ 图片 URL 类型: ${imageUrl?.startsWith('http') ? '直链' : '未知'}`);
                console.log(`[buildFilePart] ✅ 图片 URL 长度: ${imageUrl?.length} 字符`);
                console.log(`[buildFilePart] ✅ 图片 URL 前缀: ${imageUrl?.substring(0, 80)}`);
                
                // 返回 image_url 格式（兼容 OpenAI）
                return { 
                  type: "image_url" as const, 
                  image_url: { url: imageUrl as string, detail: "low" }
                };
              }

              return {
                type: "File" as const,
                url: attachment.url,
                name: attachment.name,
                mime: attachment.contentType,
                size: attachment.size,
                preview: undefined,
              };
            } catch {
              return { type: "text" as const, text: `📄 [${attachment.name}](${attachment.url})` };
            }
          };

          // 发送前清理历史图片部件（仅保留文本），避免重复拉取旧预览链接
          const prunedHistory = await Promise.all(messages.map(async (msg, index) => {
            if (index === messages.length - 1) return msg; // 跳过本轮用户消息
            try {
              const role = (msg as any).role || (msg as any).type;
              const contentArr = Array.isArray((msg as any).content) ? (msg as any).content as any[] : null;
              if (!contentArr) return msg;
              const pruned = contentArr.filter((p: any) => p?.type !== 'image' && p?.type !== 'image_url');
              return { ...msg, content: pruned } as any;
            } catch { return msg; }
          }));

          // 构造包含附件的多模态消息
          const enhancedMessages = await Promise.all(prunedHistory.map(async (msg, index) => {
            if (index === messages.length - 1 && msg.type === "human") {
              console.log(`[STREAM] 处理最后一个用户消息:`, msg);
              
              // 构造附件内容部分：图片/表格预览/通用卡片
              const attachmentParts = await Promise.all(completedAttachments.map((a) => buildFilePart(a)));

              // 过滤掉冗余的图片内容部分
              const originalParts = Array.isArray(msg.content)
                ? msg.content
                : [{ type: "text" as const, text: msg.content }];
              const filteredParts = originalParts.filter((p: any) => p?.type !== "image" && p?.type !== "image_url");

              // 为了保证先“文件气泡”再“文本气泡”，我们将附件文本链接放在内容数组最前面（已由 attachmentParts 构造）
              const enhancedMessage = {
                ...msg,
                content: [
                  ...attachmentParts,
                  ...filteredParts,
                ]
              } as any;
              
              console.log(`[STREAM] 增强后的消息:`, enhancedMessage);
              console.log(`[STREAM] 消息内容部分数量:`, enhancedMessage.content.length);
              
              // 同步修改传入的 messages，保证 UI 侧也能立即按先图后文渲染
              try { (messages as any)[index] = enhancedMessage; } catch {}

              return enhancedMessage;
            }
            return msg;
          }))
          
          console.log(`[STREAM] 发送多模态消息，包含 ${completedAttachments.length} 个附件`);
          
          // 如果是首页场景（没有 conversationId），先创建新会话
          let finalConversationId = conversationId;
          let finalThreadId = currentThreadId;

          if (!conversationId) {
            console.log(`[STREAM] 首页场景（附件）：创建新会话`);
            try {
              const response = await fetch('/api/conversations', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: '新聊天' }),
              });
              if (response.ok) {
                const newConv = await response.json();
                finalConversationId = newConv.id;
                finalThreadId = newConv.threadId || currentThreadId;
                console.log(`[STREAM] 创建新会话成功（附件）:`, { conversationId: finalConversationId, threadId: finalThreadId });
                
                // 同页：仅替换 URL，继续在本页流式
                try { window.history.replaceState({}, '', `/chat/${finalConversationId}`); } catch {}
                // 方案C：上下文层已切换，无需补派发
              } else {
                console.error(`[STREAM] 创建会话失败（附件）:`, response.status);
                throw new Error(`创建会话失败: ${response.status}`);
              }
            } catch (error) {
              console.error(`[STREAM] 创建会话异常（附件）:`, error);
              throw error;
            }
          }
          
          const tReq0 = performance.now?.() || Date.now();
          abortControllerRef.current = new AbortController();
          const streamResponse = await sendMessage({
            conversationId: finalConversationId || "",
            threadId: finalThreadId!,
            messages: enhancedMessages,
            signal: abortControllerRef.current.signal,
          });
          console.log(`[PERF front] sendMessage-called +${(performance.now?.() || Date.now()) - tReq0}ms since req`);
          
          // 清理附件：改为在 messages/complete 后进行（由 convertToLangGraphFormat 触发）
          
          return convertToLangGraphFormat(streamResponse);
        } else {
          // 没有附件，或存在图片则走图片问答
          console.log(`[STREAM] 发送普通消息`);
          
          // 如果是首页场景（没有 conversationId），先创建新会话
          let finalConversationId = conversationId;
          let finalThreadId = currentThreadId;

          if (!conversationId) {
            console.log(`[STREAM] 首页场景：创建新会话`);
            try {
              const response = await fetch('/api/conversations', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: '新聊天' }),
              });
              if (response.ok) {
                const newConv = await response.json();
                finalConversationId = newConv.id;
                finalThreadId = newConv.threadId || currentThreadId;
                console.log(`[STREAM] 创建新会话成功:`, { conversationId: finalConversationId, threadId: finalThreadId });
                
                // 同页：仅替换 URL，继续在本页流式
                try { window.history.replaceState({}, '', `/chat/${finalConversationId}`); } catch {}
                // 方案C：上下文层已切换，无需补派发
              } else {
                console.error(`[STREAM] 创建会话失败:`, response.status);
                throw new Error(`创建会话失败: ${response.status}`);
              }
            } catch (error) {
              console.error(`[STREAM] 创建会话异常:`, error);
              throw error;
            }
          }
          
          // 发送前清理历史图片部件（仅保留文本）
          const prunedMessages = messages.map((msg, idx) => {
            if (idx === messages.length - 1) return msg; // 当前用户消息无图则保持
            try {
              const contentArr = Array.isArray((msg as any).content) ? (msg as any).content as any[] : null;
              if (!contentArr) return msg;
              const pruned = contentArr.filter((p: any) => p?.type !== 'image' && p?.type !== 'image_url');
              return { ...msg, content: pruned } as any;
            } catch { return msg; }
          });

          // 直接发送消息，让 AttachmentAdapter 处理所有文件类型
          console.log(`[STREAM] 发送消息到后端，消息数量: ${prunedMessages.length}`);

          const tReq1 = performance.now?.() || Date.now();
          abortControllerRef.current = new AbortController();
          const streamResponse = await sendMessage({
            conversationId: finalConversationId || "",
            threadId: finalThreadId!,
            messages: prunedMessages,
            signal: abortControllerRef.current.signal,
          });
          console.log(`[PERF front] sendMessage-called(no-attach) +${(performance.now?.() || Date.now()) - tReq1}ms since req`);
          
          return convertToLangGraphFormat(streamResponse);
        }
      } catch (error) {
        console.error(`[STREAM] 处理错误:`, error);
        throw error;
      } finally {
        // 外层 finally 不再清理 isStreaming，清理逻辑统一在生成器 finally 中完成
        if (STREAM_DEBUG) console.log(`[STREAM] 处理完成(outer finally reached)`);
        try { if (STREAM_DEBUG) console.log(`[STREAM] runtime post-export len`, (lastValidRuntimeRef.current as any)?.export?.()?.messages?.length); } catch {}
      }
  }, [stableThreadId, conversationId]);

  const adaptersMemo = useMemo(() => ({ attachments: attachmentAdapter }), [attachmentAdapter]);

  const rawRuntime = useLangGraphRuntime({
    threadId: stableThreadId,
    stream,
    adapters: adaptersMemo,
  });

  // 保持稳定的runtime：如果rawRuntime有效则使用它，否则使用最后一个有效的runtime
  const runtime = useMemo(() => {
    if (rawRuntime) {
      lastValidRuntimeRef.current = rawRuntime;
      return rawRuntime;
    }
    // 如果rawRuntime为空，使用最后一个有效的runtime避免消息历史消失
    return lastValidRuntimeRef.current;
  }, [rawRuntime]);

  // 首页：在 runtime 就绪后做一次 reset，清空旧消息，随后标记 hasHomeReset=true
  useEffect(() => {
    (async () => {
      try {
        if (conversationId) return; // 仅首页
        if (!runtime) return;
        if (hasHomeReset) return;
        try {
          if (typeof (runtime as any)?.reset === 'function') {
            console.log('[RT] reset:home runtime before');
            await (runtime as any).reset();
            console.log('[RT] reset:home runtime after', (runtime as any)?.export?.()?.messages?.length);
          }
        } catch (e) {
          console.warn('[RT] reset:home runtime failed', e);
        }
        setHasHomeReset(true);
      } catch {}
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId, runtime, hasHomeReset]);

  // 调试：挂载只读句柄到 window，跟踪 runtime 生命周期
  useEffect(() => {
    try {
      const rid = runtimeIdRef.current;
      (window as any).__AUI_RT__ = { runtime, runtimeId: rid, conversationId };
      console.log(`[RT] mount`, { runtimeId: rid, conversationId });
      return () => {
        try {
          console.log(`[RT] unmount`, { runtimeId: rid, conversationId });
          if ((window as any).__AUI_RT__?.runtime === runtime) {
            delete (window as any).__AUI_RT__;
          }
        } catch {}
      };
    } catch {}
  }, [runtime, conversationId]);

  // 提供 cancelStreaming：取消当前 SSE 读取（上移，确保 hooks 顺序稳定）
  const cancelStreaming = useCallback(() => {
    try {
      // 只负责 UI 状态与生成器完成通知，不调用 ThreadRuntime 的 cancelRun（该实现不支持）
      if (isStreamingRef.current) {
        console.log('[RT] cancelStreaming: user requested');
        try { abortControllerRef.current?.abort(); } catch {}
        try { setIsStreaming(false); } catch {}
        try { streamDoneRef.current?.resolve(); } catch {}
        isStreamingRef.current = false;
      }
    } catch {}
  }, []);

  // 只在 stableThreadId 确定且从未有过有效runtime时才显示Loading
  // 如果曾经有过有效的runtime，即使当前rawRuntime为空也要保持界面稳定
  if (!stableThreadId || (!runtime && !lastValidRuntimeRef.current)) {
    console.log(`[RT] Waiting for threadId or initial runtime...`, { 
      conversationId, 
      hasThreadId: !!stableThreadId, 
      hasRuntime: !!runtime,
      hasLastValidRuntime: !!lastValidRuntimeRef.current
    });
    return <div>Loading...</div>;
  }

  return (
    <ChatUIContext.Provider value={{ isChatting: uiIsChatting, setIsChatting: setUiIsChatting, hasHomeReset, setHasHomeReset, isStreaming, setIsStreaming, cancelStreaming }}>
      <AssistantRuntimeProvider runtime={runtime}>
        {children}
      </AssistantRuntimeProvider>
    </ChatUIContext.Provider>
  );
}


// 调试：在 Provider 层观察 runtime 的生命周期与 import/export 调用（不改变行为）
// 将在 runtime 变更时打点，并将只读引用挂到 window 便于控制台比对
// 注意：这些日志可随时移除，不影响功能

// 移除 MessageAppender 组件，返回到原始的 UI 更新机制

// 组件外不做实例级日志

