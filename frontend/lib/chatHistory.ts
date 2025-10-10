"use client";

export type ChatSummary = {
  id: string;
  title: string;
  updatedAt: number;
};

const SUMMARIES_KEY = "aui:chat:summaries";
const MESSAGES_KEY_PREFIX = "aui:chat:messages:";
const EVENT_SUMMARIES_CHANGED = "aui:chat:summaries-changed";
const DRAFT_ID_KEY = "aui:chat:draft-id";
const REPO_KEY_PREFIX = "aui:chat:repo:";

function isBrowser() {
  return typeof window !== "undefined" && typeof localStorage !== "undefined";
}

function readSummaries(): ChatSummary[] {
  if (!isBrowser()) return [];
  try {
    const raw = localStorage.getItem(SUMMARIES_KEY);
    if (!raw) return [];
    const list = JSON.parse(raw) as ChatSummary[];
    return Array.isArray(list) ? list : [];
  } catch {
    return [];
  }
}

function writeSummaries(list: ChatSummary[]) {
  if (!isBrowser()) return;
  try {
    localStorage.setItem(SUMMARIES_KEY, JSON.stringify(list));
    window.dispatchEvent(new CustomEvent(EVENT_SUMMARIES_CHANGED));
  } catch {}
}

export function getAllSummaries(): ChatSummary[] {
  return readSummaries().sort((a, b) => b.updatedAt - a.updatedAt);
}

export function onSummariesChanged(handler: () => void) {
  if (!isBrowser()) return () => {};
  const cb = () => handler();
  window.addEventListener(EVENT_SUMMARIES_CHANGED, cb);
  return () => window.removeEventListener(EVENT_SUMMARIES_CHANGED, cb);
}

function upsertSummary(next: ChatSummary) {
  const list = readSummaries();
  const idx = list.findIndex((x) => x.id === next.id);
  if (idx >= 0) list[idx] = next; else list.push(next);
  writeSummaries(list);
}

function extractTextFromMessage(message: any): string | undefined {
  try {
    if (!message) return undefined;
    if (typeof message === "string") return message;
    if (message.content && typeof message.content === "string") return message.content;
    if (Array.isArray(message.content) && message.content[0]?.text) return message.content[0].text as string;
    if (message.text) return String(message.text);
    if (Array.isArray(message.parts) && message.parts[0]?.text) return String(message.parts[0].text);
  } catch {}
  return undefined;
}

function inferTitleFromMessages(messages: any[]): string {
  const firstUser = (messages || []).find((m: any) => m?.role === "user");
  const candidate = extractTextFromMessage(firstUser) || extractTextFromMessage(messages?.[0]);
  const text = (candidate || "新聊天").trim();
  return text.length > 40 ? text.slice(0, 40) : text;
}

export function saveMessages(id: string, messages: any[]) {
  if (!isBrowser()) return;
  try {
    localStorage.setItem(MESSAGES_KEY_PREFIX + id, JSON.stringify(messages ?? []));
  } catch {}
}

export function getMessages(id: string): any[] {
  if (!isBrowser()) return [];
  try {
    // 优先从仓库结构读取
    const repoRaw = localStorage.getItem(REPO_KEY_PREFIX + id);
    if (repoRaw) {
      const repo = JSON.parse(repoRaw) as { messages?: Array<{ parentId: string | null; message: any }>; };
      if (repo && Array.isArray(repo.messages)) {
        return repo.messages.map((m) => m.message);
      }
    }
    // 兼容旧键
    const raw = localStorage.getItem(MESSAGES_KEY_PREFIX + id);
    return raw ? (JSON.parse(raw) as any[]) : [];
  } catch {
    return [];
  }
}

export function removeChat(id: string) {
  if (!isBrowser()) return;
  try {
    const list = readSummaries().filter((x) => x.id !== id);
    writeSummaries(list);
    localStorage.removeItem(MESSAGES_KEY_PREFIX + id);
    localStorage.removeItem(REPO_KEY_PREFIX + id);
  } catch {}
}

// 归档聊天（软删除）
export function archiveChat(id: string) {
  if (!isBrowser()) return;
  try {
    // 从本地存储摘要中移除，但保留消息数据
    const list = readSummaries().filter((x) => x.id !== id);
    writeSummaries(list);
  } catch {}
}

export function upsertChatFromThread(id: string, messages: any[]) {
  if (!Array.isArray(messages) || messages.length === 0) return;
  const now = Date.now();
  const title = inferTitleFromMessages(messages);
  upsertSummary({ id, title, updatedAt: now });
  saveMessages(id, messages);
}

// 草稿会话：无消息的临时会话 id
export function getDraftId(): string | null {
  if (!isBrowser()) return null;
  try {
    return localStorage.getItem(DRAFT_ID_KEY);
  } catch {
    return null;
  }
}

export function setDraftId(id: string | null) {
  if (!isBrowser()) return;
  try {
    if (id) localStorage.setItem(DRAFT_ID_KEY, id);
    else localStorage.removeItem(DRAFT_ID_KEY);
  } catch {}
}

// 根据消息变化更新草稿与历史
export function updateDraftAndHistory(id: string, messages: any[]) {
  if (!Array.isArray(messages) || messages.length === 0) {
    // 若已有持久化的历史消息，则这是一次导航到历史会话的初始空渲染，不应删除
    const persisted = getMessages(id);
    if (Array.isArray(persisted) && persisted.length > 0) {
      return;
    }
    // 否则当作草稿：记录草稿 id，但不写入历史
    setDraftId(id);
    // 兜底：移除可能残留的空历史
    removeChat(id);
    return;
  }
  // 有消息：清理草稿并写入历史
  const draft = getDraftId();
  if (draft === id) setDraftId(null);
  upsertChatFromThread(id, messages);
}

// -------- 基于库的导入/导出存取（历史回灌用） --------
export type ExportedMessageRepository = {
  headId?: string | null;
  messages: Array<{ parentId: string | null; message: any }>;
};

export function saveRepo(id: string, repo: ExportedMessageRepository) {
  if (!isBrowser()) return;
  try {
    localStorage.setItem(REPO_KEY_PREFIX + id, JSON.stringify(repo));
  } catch {}
}

export function getRepo(id: string): ExportedMessageRepository | null {
  if (!isBrowser()) return null;
  try {
    const raw = localStorage.getItem(REPO_KEY_PREFIX + id);
    return raw ? (JSON.parse(raw) as ExportedMessageRepository) : null;
  } catch {
    return null;
  }
}