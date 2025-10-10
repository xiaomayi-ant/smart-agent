import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// 统一规范图片 URL：
// - 绝对 URL：原样返回
// - 以 /uploads/ 开头：补上和后端一致的端口 :3001（避免 Next 3000 端口读取不到）
// - 其他相对路径：相对当前 origin 解析
export function normalizeImageSrc(src?: string): string | undefined {
  if (!src) return undefined;
  try {
    if (/^https?:\/\//i.test(src)) return src;
    if (src.startsWith('/uploads/')) {
      const { protocol, hostname } = window.location;
      return `${protocol}//${hostname}:3001${src}`;
    }
    return new URL(src, window.location.origin).href;
  } catch {
    return src;
  }
}
