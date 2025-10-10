"use client";

import React, { createContext, useContext } from "react";

export interface ChatUIContextValue {
  isChatting: boolean;
  setIsChatting: (value: boolean) => void;
  hasHomeReset?: boolean;
  setHasHomeReset?: (value: boolean) => void;
}

export const ChatUIContext = createContext<ChatUIContextValue | null>(null);

export function useChatUI(): ChatUIContextValue {
  const ctx = useContext(ChatUIContext);
  if (!ctx) {
    throw new Error("useChatUI must be used within a ChatUIContext provider");
  }
  return ctx;
}


