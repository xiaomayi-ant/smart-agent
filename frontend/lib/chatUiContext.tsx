"use client";

import React, { createContext, useContext } from "react";

export interface ChatUIContextValue {
  isChatting: boolean;
  setIsChatting: (value: boolean) => void;
  hasHomeReset?: boolean;
  setHasHomeReset?: (value: boolean) => void;
  // 流式运行态（供三态按钮显示“中止”）
  isStreaming?: boolean;
  setIsStreaming?: (value: boolean) => void;
  // 主动中止当前流
  cancelStreaming?: () => void;
}

export const ChatUIContext = createContext<ChatUIContextValue | null>(null);

export function useChatUI(): ChatUIContextValue {
  const ctx = useContext(ChatUIContext);
  if (!ctx) {
    throw new Error("useChatUI must be used within a ChatUIContext provider");
  }
  return ctx;
}


