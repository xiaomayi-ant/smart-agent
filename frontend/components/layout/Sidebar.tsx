"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { useEffect, useState } from "react";
import { SquarePen, Search, Images, Settings, ChevronsLeft, ChevronsRight, MoreHorizontal, Trash2, Share } from "lucide-react";
import { getAllSummaries, onSummariesChanged, type ChatSummary, getDraftId, setDraftId, removeChat } from "@/lib/chatHistory";
import { DropdownMenu, DropdownMenuItem, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";

export function Sidebar() {
  const router = useRouter();
  const [collapsed, setCollapsed] = useState(false);
  const [history, setHistory] = useState<ChatSummary[]>([]);
  const [serverItems, setServerItems] = useState<Array<{ id: string; title: string; updatedAt: string }>>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [deletingIds, setDeletingIds] = useState<Set<string>>(new Set());
  const [visibleCount, setVisibleCount] = useState(10);

  // 初始化：从 localStorage 读取折叠状态
  useEffect(() => {
    try {
      const raw = localStorage.getItem("sidebar-collapsed");
      if (raw != null) setCollapsed(raw === "1");
    } catch {}
  }, []);

  // 折叠状态 → 同步到全局 CSS 变量，驱动外层栅格与覆盖层自适应
  useEffect(() => {
    try {
      const value = collapsed ? "var(--sidebar-w-collapsed)" : "var(--sidebar-w-expanded)";
      document.documentElement.style.setProperty("--sidebar-w", value);
    } catch {}
  }, [collapsed]);

  // 初始化与订阅：本地聊天历史（保留作为兜底）
  useEffect(() => {
    try {
      setHistory(getAllSummaries());
      const off = onSummariesChanged(() => setHistory(getAllSummaries()));
      return () => off();
    } catch {}
  }, []);

  async function fetchFirstPage() {
    try {
      setLoading(true);
      const resp = await fetch(`/api/conversations?take=30`, { cache: "no-store" });
      if (resp.ok) {
        const data = await resp.json();
        setServerItems(data?.items || []);
        setNextCursor(data?.nextCursor || null);
        setVisibleCount(10);
      }
    } catch {}
    finally { setLoading(false); }
  }

  // 首屏加载 + 订阅刷新事件/焦点回到页面时刷新 + 轻量轮询
  useEffect(() => {
    fetchFirstPage();
    const onRefresh = () => fetchFirstPage();
    const onVisibility = () => { if (document.visibilityState === "visible") fetchFirstPage(); };
    window.addEventListener("aui:conv-refresh", onRefresh as any);
    window.addEventListener("visibilitychange", onVisibility);
    const timer = window.setInterval(() => fetchFirstPage(), 10000);
    return () => {
      window.removeEventListener("aui:conv-refresh", onRefresh as any);
      window.removeEventListener("visibilitychange", onVisibility);
      window.clearInterval(timer);
    };
  }, []);

  const loadMore = async () => {
    if (!nextCursor || loading) return;
    try {
      setLoading(true);
      const resp = await fetch(`/api/conversations?take=30&cursor=${encodeURIComponent(nextCursor)}`, { cache: "no-store" });
      if (resp.ok) {
        const data = await resp.json();
        setServerItems((prev) => [...prev, ...(data?.items || [])]);
        setNextCursor(data?.nextCursor || null);
      }
    } catch {}
    finally { setLoading(false); }
  };

  // 删除会话 - 永久删除，确保数据库同步
  const handleDeleteChat = async (id: string, e: React.MouseEvent) => {

    e.preventDefault();
    e.stopPropagation();
    
    if (deletingIds.has(id)) return;
    
    const isConfirmed = window.confirm("确定要永久删除这个会话及其所有消息吗？此操作不可恢复！");
    if (!isConfirmed) return;
    
    setDeletingIds(prev => new Set(prev).add(id));
    
    let serverDeleteSuccess = false;
    let retryCount = 0;
    const maxRetries = 3;
    
    // 重试机制确保数据库操作成功
    while (retryCount < maxRetries && !serverDeleteSuccess) {
      try {

        
        const response = await fetch(`/api/conversations/${id}`, {
          method: 'DELETE',
          headers: { 
            'Cache-Control': 'no-cache'
          }
        });
        
        if (response.ok) {
          const result = await response.json();

          serverDeleteSuccess = true;
          
          // 服务器删除成功，更新本地状态
          setServerItems(prev => prev.filter(item => item.id !== id));
          // 同时也清理本地存储
          removeChat(id);
          // 触发全局刷新事件
          window.dispatchEvent(new CustomEvent("aui:conv-refresh"));
          
          // 会话已成功归档
          
        } else {
          const errorData = await response.json().catch(() => ({}));
          console.error(`服务器删除失败 (${response.status}):`, errorData);
          retryCount++;
          
          if (retryCount < maxRetries) {
            // 等待后重试
            await new Promise(resolve => setTimeout(resolve, 1000 * retryCount));
          }
        }
      } catch (error) {
        console.error(`删除会话网络错误 (尝试 ${retryCount + 1}):`, error);
        retryCount++;
        
        if (retryCount < maxRetries) {
          // 等待后重试
          await new Promise(resolve => setTimeout(resolve, 1000 * retryCount));
        }
      }
    }
    
    // 如果服务器操作失败，但仍然清理本地存储（降级处理）
    if (!serverDeleteSuccess) {
      console.warn('服务器删除失败，仅清理本地存储');
      removeChat(id);
      setHistory(prev => prev.filter(item => item.id !== id));
      
      // 显示警告消息
      alert('删除操作可能未完全同步到服务器，建议刷新页面确认');
    }
    
    // 最终清理删除状态
    setDeletingIds(prev => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  };

  // 分享会话
  const handleShareChat = async (id: string, title: string, e: React.MouseEvent) => {

    
    try {
      // 生成分享链接
      const shareUrl = `${window.location.origin}/chat/${id}`;
      
      if (navigator.share) {
        // 使用原生分享API（移动设备）
        await navigator.share({
          title: `分享聊天: ${title}`,
          url: shareUrl,
        });
      } else {
        // 复制到剪贴板
        await navigator.clipboard.writeText(shareUrl);
        // 这里可以添加一个toast提示，暂时用alert代替
        alert("链接已复制到剪贴板");
      }
    } catch (error) {
      console.error("分享失败:", error);
      // 降级方案：手动复制
      const shareUrl = `${window.location.origin}/chat/${id}`;
      try {
        await navigator.clipboard.writeText(shareUrl);
        alert("链接已复制到剪贴板");
      } catch {
        alert(`请手动复制链接: ${shareUrl}`);
      }
    }
  };

  // 写入持久化
  const toggleCollapsed = () => {
    setCollapsed((v) => {
      const next = !v;
      try {
        localStorage.setItem("sidebar-collapsed", next ? "1" : "0");
      } catch {}
      return next;
    });
  };
  return (
    <aside
      className={cn(
        "hidden md:flex shrink-0 border-r bg-[#f9f9f9] text-card-foreground w-full text-sm"
      )}
    >
      <div className="flex h-dvh w-full flex-col">
        {/* 顶部：Logo A + 关闭按钮 */}
        <div className="sticky top-0 z-10 flex h-12 items-center justify-between bg-[#f9f9f9] px-3">
          <Link
            href="/"
            aria-label="主页"
            className="flex h-9 w-9 items-center justify-center rounded-lg hover:bg-muted"
          >
            <span
              className="flex h-7 w-7 items-center justify-center rounded-md text-[18px] font-black italic leading-none"
              style={{ color: "#30D5C8" }}
            >
              A
            </span>
          </Link>
          <button
            aria-label={collapsed ? "展开侧栏" : "折叠侧栏"}
            className="flex h-10 w-10 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted"
            onClick={toggleCollapsed}
          >
            {collapsed ? (
              <ChevronsRight className="h-6 w-6" />
            ) : (
              <ChevronsLeft className="h-6 w-6" />
            )}
          </button>
        </div>

        {/* 导航组：新聊天/搜索聊天/库（顶部固定区）*/}
        <nav className="px-3 py-3">
          <ul className="mt-3 space-y-1">
            <li>
              <button
                className="group flex w-full items-center gap-2 rounded-lg px-2 h-10 hover:bg-muted"
                onClick={async () => {
                  try {
                    console.log('[SIDEBAR] new-chat: start', { href: location.href });
                    const resp = await fetch('/api/conversations', {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ title: '新聊天' }),
                    });
                    if (!resp.ok) {
                      const t = await resp.text().catch(() => '');
                      console.error('[SIDEBAR] new-chat: server error', resp.status, t);
                      // 兜底回到首页
                      router.push('/');
                      return;
                    }
                    const data = await resp.json();
                    console.log('[SIDEBAR] new-chat: created', data);
                    const newId = data?.id;
                    const tid = typeof data?.threadId === 'string' ? data.threadId : '';
                    if (typeof newId === 'string' && newId) {
                      // 直接跳到新会话页
                      const qs = tid ? `?new=1&tid=${encodeURIComponent(tid)}` : `?new=1`;
                      router.push(`/chat/${newId}${qs}`);
                      setTimeout(() => {
                        try {
                          console.log('[SIDEBAR] new-chat: after push', { href: location.href, newId });
                        } catch {}
                      }, 0);
                    } else {
                      console.warn('[SIDEBAR] new-chat: invalid id in response, fallback to /');
                      router.push('/');
                    }
                  } catch (e) {
                    console.error('[SIDEBAR] new-chat: exception', e);
                    router.push('/');
                  }
                }}
              >
                <SquarePen className="h-5 w-5 text-muted-foreground group-hover:text-foreground" strokeWidth={1.5} />
                {!collapsed && (
                  <span className="text-sm text-foreground/90 group-hover:text-foreground">新聊天</span>
                )}
              </button>
            </li>
            <li>
              <button className="group flex w-full items-center gap-2 rounded-lg px-2 h-10 hover:bg-muted">
                <Search className="h-5 w-5 text-muted-foreground group-hover:text-foreground" strokeWidth={1.5} />
                {!collapsed && (
                  <span className="text-sm text-foreground/90 group-hover:text-foreground">搜索聊天</span>
                )}
              </button>
            </li>
            <li>
              <Link
                href="/library"
                className="group flex items-center gap-2 rounded-lg px-2 h-10 hover:bg-muted"
              >
                <Images className="h-5 w-5 text-muted-foreground group-hover:text-foreground" strokeWidth={1.5} />
                {!collapsed && (
                  <span className="text-sm text-foreground/90 group-hover:text-foreground">库</span>
                )}
              </Link>
            </li>
          </ul>
        </nav>

        {/* 历史会话列表（折叠时完全不显示，中部留空以保持底部贴底） */}
        {collapsed ? (
          <div className="flex-1" />
        ) : (
          <section className="mt-2 flex-1 overflow-auto px-3 pb-2" onScroll={(e) => {
            const el = e.currentTarget;
            if (el.scrollTop + el.clientHeight >= el.scrollHeight - 24) {
              loadMore();
            }
          }}>
            {(serverItems.length > 0 || loading) && (
              <>
                <div className="px-2 pt-2 pb-1 text-xs text-muted-foreground/70">历史聊天</div>
                <ul className="space-y-1">
                  {serverItems.slice(0, Math.max(0, visibleCount)).map((h) => (
                    <li key={`server-${h.id}`} className="group/item relative">
                      <Link
                        href={`/chat/${h.id}`}
                        prefetch={false}
                        className="group flex w-full items-center gap-2 rounded-lg px-2 py-2 hover:bg-muted text-left pr-10"
                        title={h.title}
                      >
                        <span className="line-clamp-1 text-sm text-foreground/90 group-hover:text-foreground flex-1">
                          {h.title || "未命名会话"}
                        </span>
                      </Link>
                      
                      {/* 悬停时显示的更多菜单 */}
                      <div className="absolute right-0 top-1/2 -translate-y-1/2 opacity-0 group-hover/item:opacity-100 transition-opacity z-50">
                        <DropdownMenu
                          trigger={
                            <button
                              className="flex h-6 w-6 items-center justify-center rounded hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
                              title="更多选项"
                            >
                              <MoreHorizontal className="h-3 w-3" />
                            </button>
                          }
                          align="right"
                        >
                          <DropdownMenuItem
                            onClick={(e) => {
                              if (e) handleShareChat(h.id, h.title, e);
                            }}
                          >
                            <div className="flex items-center gap-2">
                              <Share className="h-3 w-3" />
                              <span>分享</span>
                            </div>
                          </DropdownMenuItem>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem
                            onClick={(e) => {
                              if (e) handleDeleteChat(h.id, e);
                            }}
                            disabled={deletingIds.has(h.id)}
                          >
                            <div className="flex items-center gap-2">
                              <Trash2 className="h-3 w-3" />
                              <span>{deletingIds.has(h.id) ? "删除中..." : "删除"}</span>
                            </div>
                          </DropdownMenuItem>
                        </DropdownMenu>
                      </div>
                    </li>
                  ))}
                  {serverItems.length > visibleCount && (
                    <div className="px-2 py-2">
                      <button
                        className="w-full text-center rounded-md bg-muted hover:bg-muted/80 h-8"
                        onClick={() => setVisibleCount((c) => c + 10)}
                      >
                        查看更多
                      </button>
                    </div>
                  )}
                  {/* 首屏未返回服务端数据时，仅显示加载文案/骨架 */}
                </ul>
                {loading && <div className="px-2 py-2 text-xs text-muted-foreground/70">加载中…</div>}
                {!nextCursor && serverItems.length > 0 && <div className="px-2 py-2 text-[11px] text-muted-foreground/60">没有更多了</div>}
              </>
            )}
          </section>
        )}

        {/* 底部设置/账号 */}
        <div className="p-3">
          <Link
            href="/settings"
            className="flex items-center gap-2 rounded px-2 py-1.5 hover:bg-muted"
          >
            <Settings className="h-4 w-4" />
            {!collapsed && <span className="text-sm">设置</span>}
          </Link>
        </div>
      </div>
    </aside>
  );
}