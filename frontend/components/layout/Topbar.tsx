"use client";

import { Button } from "@/components/ui/button";
import { ChevronDown, Mic, MoreHorizontal } from "lucide-react";
import { useEffect, useRef } from "react";

export function Topbar() {
  const ref = useRef<HTMLElement | null>(null);

  useEffect(() => {
    try {
      // 固定顶部栏高度变量，避免首次与后续测量带来的细微抖动
      document.documentElement.style.setProperty("--topbar-h", "56px");
    } catch {}
  }, []);

  return (
    <header ref={ref} className="sticky top-0 z-20 bg-background h-14">
      <div className="flex h-full items-center gap-3 px-4">
        {/* 左侧：模型选择（占位） */}
        <Button variant="ghost" className="font-semibold">
          ChatGPT 5 <ChevronDown className="ml-1 h-4 w-4" />
        </Button>

        {/* 中间：留空，让布局更简洁 */}
        <div className="flex-1" />

        {/* 右侧更多 */}
        <Button variant="ghost" size="icon">
          <MoreHorizontal className="h-5 w-5" />
        </Button>
      </div>
    </header>
  );
}
