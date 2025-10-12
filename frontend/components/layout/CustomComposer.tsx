"use client";

import { Mic, Plus, AudioLines, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Composer as UIComposer, useThreadRuntime, ComposerPrimitive } from "@assistant-ui/react";
import { useComposerRuntime } from "@assistant-ui/react";
import { useDictation } from "@/app/hooks/useDictation";
import { useState, useCallback, useEffect, useRef } from "react";
import { useChatUI } from "@/lib/chatUiContext";

export function CustomComposer() {
  const composer = useComposerRuntime();
  const threadRuntime = useThreadRuntime();
  const { isStreaming, setIsStreaming, cancelStreaming } = useChatUI();
  const { isRecording, isBusy, start, stop } = useDictation();
  const [hint, setHint] = useState<string>("");
  const composingRef = useRef<boolean>(false);

  // 监控 isStreaming 变化
  useEffect(() => {
    console.log('[CustomComposer] isStreaming 变化:', isStreaming);
    console.log('[CustomComposer] setIsStreaming 可用:', !!setIsStreaming);
  }, [isStreaming, setIsStreaming]);

  const [hasSendable, setHasSendable] = useState<boolean>(() => {
    try {
      const st: any = composer.getState?.() ?? {};
      const text = (st.text ?? "").trim();
      const atts = Array.isArray(st.attachments) ? st.attachments : [];
      return (text.length > 0) || atts.length > 0;
    } catch {
      return false;
    }
  });

  const recalc = useCallback(() => {
    try {
      // 冻结：输入法合成期不刷新 hasSendable，避免发送/语音闪烁
      if (composingRef.current) return;
      const st: any = composer.getState?.() ?? {};
      const raw = (st.text ?? "").trim();
      const atts = Array.isArray(st.attachments) ? st.attachments : [];
      const hasText = !composingRef.current && raw.length > 0;
      const hasAttachments = atts.length > 0;
      setHasSendable(hasText || hasAttachments);
    } catch {}
  }, [composer]);

  useEffect(() => {
    let stopped = false;
    // 优先尝试订阅（若库支持）
    const anyComposer: any = composer as any;
    if (anyComposer && typeof anyComposer.subscribe === "function") {
      const unsub = anyComposer.subscribe(() => {
        if (stopped) return;
        try {
          if ("requestIdleCallback" in window) {
            (window as any).requestIdleCallback(recalc, { timeout: 200 });
          } else {
            requestAnimationFrame(recalc);
          }
        } catch {
          recalc();
        }
      });
      recalc();
      return () => { stopped = true; try { unsub?.(); } catch {} };
    }
    // 兜底观察：节流轮询附件长度与文本大致变化
    recalc();
    let lastLen = -1;
    const tick = () => {
      if (stopped) return;
      try {
        const st: any = composer.getState?.() ?? {};
        const len = Array.isArray(st.attachments) ? st.attachments.length : 0;
        const tlen = (st.text ?? "").length;
        if (len !== lastLen || tlen % 5 === 0) {
          lastLen = len;
          recalc();
        }
      } catch {}
      setTimeout(() => { if (!stopped) requestAnimationFrame(tick); }, 500);
    };
    tick();
    return () => { stopped = true; };
  }, [composer, recalc]);

  const handleCancel = useCallback(() => {
    try {
      // 当前 runtime 不支持 cancelRun；改为通过 Provider 提供的 cancelStreaming 终止 UI 与读取
      if (typeof cancelStreaming === 'function') {
        cancelStreaming();
      } else {
        // 兜底：直接标记结束
        setIsStreaming?.(false);
      }
    } catch (e) {
      console.error('[Composer] 取消失败:', e);
    }
  }, [cancelStreaming, setIsStreaming]);

  const handleStart = useCallback(async () => {
    try {
      setHint("正在录音…松开结束");
      await start();
    } catch (e) {
      setHint("无法开始录音，请检查麦克风权限");
    }
  }, [start]);

  const handleStop = useCallback(async () => {
    try {
      setHint("正在转写…");
      const res = await stop();
      if (res && res.text) {
        const prev = composer.getState().text || "";
        const next = prev ? `${prev.trim()} ${res.text}` : res.text;
        composer.setText(next);
        try { recalc(); } catch {}
        // 音频已上传到OSS存档，不在聊天界面显示附件
      }
    } finally {
      setHint("");
    }
  }, [stop, composer, recalc]);

  return (
    <UIComposer.Root className="aui-composer-root grid grid-cols-[auto_1fr_auto] items-center gap-0 [grid-template-areas:'attachments_attachments_attachments'_'leading_primary_trailing']">
      {/* 使用 Assistant-UI 内置的附件显示（加作用域类供样式命中） */}
      <div className="aui-composer-attachments [grid-area:attachments]">
        <UIComposer.Attachments />
      </div>

      {/* leading: 附件按钮（使用 Primitive 以移除 Tooltip） */}
      <div className="[grid-area:leading] relative">
        <ComposerPrimitive.AddAttachment asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="add-attachment"
            className="rounded-full w-8 h-8 text-foreground/80 hover:text-foreground"
          >
            <Plus className="h-4 w-4" />
          </Button>
        </ComposerPrimitive.AddAttachment>
      </div>

      {/* primary: 输入区 */}
      <div className="aui-composer-primary [grid-area:primary] min-h-9 flex items-start gap-2 text-left">
        <UIComposer.Input
          className="aui-composer-input w-full text-left flex-1 min-w-0"
          placeholder={hint || ""}
          onInput={() => { if (!composingRef.current) recalc(); }}
          onCompositionStart={() => { composingRef.current = true; }}
          onCompositionEnd={() => { composingRef.current = false; recalc(); }}
        />
      </div>

      {/* trailing: 麦克风 + (发送/取消/语音) */}
      <div className="[grid-area:trailing] flex items-center gap-2">
        {/* 调试标签已移除 */}
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label="mic"
          className="rounded-full w-8 h-8 text-foreground/80 hover:text-foreground"
          onMouseDown={handleStart}
          onMouseUp={handleStop}
          onTouchStart={handleStart}
          onTouchEnd={handleStop}
          disabled={isBusy}
        >
          <Mic className={`h-4 w-4 ${isRecording ? 'text-red-500' : ''}`} />
        </Button>
        {isStreaming ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="stop"
            className="w-8 h-8 rounded-full bg-muted hover:bg-muted/80 shadow-inner ring-1 ring-black/5 flex items-center justify-center"
            onClick={handleCancel}
          >
            <div className="w-3 h-3 rounded-[4px] bg-black" />
          </Button>
        ) : hasSendable ? (
          <UIComposer.Action />
        ) : (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="voice"
            className="rounded-full w-8 h-8 text-foreground/80 hover:text-foreground"
            onClick={() => {
              try {
                const m = typeof window !== 'undefined' ? window.location.pathname.match(/\/chat\/([^\/?]+)/) : null;
                const q = m?.[1] ? `?conversationId=${m[1]}` : '';
                window.location.assign(`/voice${q}`);
              } catch {}
            }}
          >
            <AudioLines className="h-4 w-4" />
          </Button>
        )}
      </div>
    </UIComposer.Root>
  );
}

export default CustomComposer;


