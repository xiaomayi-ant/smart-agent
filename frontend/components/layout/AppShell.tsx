"use client";

import { ReactNode, useEffect, useRef } from "react";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

export function AppShell({ children }: { children: ReactNode }) {
  const overlayInnerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    try {
      const el = overlayInnerRef.current;
      if (!el) return;
      const update = () => {
        const h = Math.round(el.getBoundingClientRect().height);
        document.documentElement.style.setProperty("--composer-h", `${h}px`);
      };
      const ro = new ResizeObserver(() => update());
      ro.observe(el);
      update();
      const onResize = () => update();
      window.addEventListener("resize", onResize);
      return () => {
        ro.disconnect();
        window.removeEventListener("resize", onResize);
      };
    } catch {}
  }, []);


  return (
    <div className="h-dvh grid grid-cols-[var(--sidebar-w)_1fr]">
      {/* 左侧：外层禁滚，保留内部中部容器滚动，避免折叠时出现外层滚动条 */}
      <aside className="bg-background overflow-hidden">
        <Sidebar />
      </aside>

      {/* 右侧主区：作为唯一滚动容器 */}
      <main className="relative overflow-y-auto min-w-0">
        <div className="min-h-full flex flex-col">
          <Topbar />
          <div className="flex-1 min-h-0 flex flex-col py-8">{children}</div>
        </div>
      </main>

      {/* 覆盖层输入区：不随主区滚动（作为 Portal 容器，由页面注入实际内容） */}
      <div className="app-composer-overlay pointer-events-none fixed right-0 bottom-0 z-50" style={{ left: "var(--sidebar-w)" }}>
        <div
          ref={overlayInnerRef}
          className="pointer-events-auto mx-auto w-full px-6 md:px-10 lg:px-14 py-3"
          style={{
            maxWidth: "calc((var(--chat-max-w) + 2 * 3.5rem) * 6/7)"
          }}
        >
          <div id="composer-host" />
        </div>
      </div>

    </div>
  );
}
