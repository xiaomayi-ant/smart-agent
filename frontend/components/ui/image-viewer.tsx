"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { X, ZoomIn } from "lucide-react";

interface ImageViewerProps {
  src: string;
  alt?: string;
  className?: string;
  thumbnailUrl?: string;
}

export function ImageViewer({ src, alt = "", className = "", thumbnailUrl }: ImageViewerProps) {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [imageLoaded, setImageLoaded] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [activeSrc, setActiveSrc] = useState<string>(src);
  const [triedProxy, setTriedProxy] = useState(false);
  const timeoutRef = useRef<number | null>(null);

  const makeProxyUrl = (u: string) => `/api/preview/image?u=${encodeURIComponent(u)}`;

  const displaySrc = thumbnailUrl || src;

  const handleClick = () => {
    try { console.log('ImageViewer clicked!', { src, displaySrc, thumbnailUrl }); } catch {}
    // 打开前重置加载状态
    setImageLoaded(false);
    setLoadError(false);
    setTriedProxy(false);
    setActiveSrc(src);
    setIsModalOpen(true);
  };

  // 打开弹窗时：锁定页面滚动，并监听 ESC 关闭
  useEffect(() => {
    if (!isModalOpen) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKeyDown = (e: KeyboardEvent) => { if (e.key === "Escape") setIsModalOpen(false); };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = prevOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [isModalOpen]);

  // 弹窗开启后，设置超时回落到代理
  useEffect(() => {
    if (!isModalOpen) {
      if (timeoutRef.current) { clearTimeout(timeoutRef.current); timeoutRef.current = null; }
      return;
    }
    if (timeoutRef.current) { clearTimeout(timeoutRef.current); }
    timeoutRef.current = window.setTimeout(() => {
      if (!imageLoaded && !loadError && !triedProxy) {
        setActiveSrc(makeProxyUrl(src));
        setTriedProxy(true);
      }
    }, 1600);
    return () => { if (timeoutRef.current) { clearTimeout(timeoutRef.current); timeoutRef.current = null; } };
  }, [isModalOpen, imageLoaded, loadError, triedProxy, src]);

  return (
    <>
      {/* 缩略图 */}
      <div 
        className={`relative inline-block cursor-pointer group ${className}`}
        onClick={handleClick}
        style={{ width: 'auto', height: 'auto' }}
      >
        <img 
          src={displaySrc} 
          alt={alt}
          className="custom-image-thumbnail rounded-lg border border-border"
        />
        {/* 悬浮放大镜图标 */}
        <div className="absolute inset-0 bg-black bg-opacity-0 group-hover:bg-opacity-20 transition-all duration-200 rounded-lg flex items-center justify-center">
          <ZoomIn className="w-6 h-6 text-white opacity-0 group-hover:opacity-100 transition-opacity duration-200" />
        </div>
      </div>

      {/* 全屏模态框（Portal 到 body，避免被父容器裁剪） */}
      {isModalOpen && createPortal(
        <div className="aui-image-lightbox fixed inset-0 z-[1000]">
          {/* 遮罩 */}
          <div className="absolute inset-0 bg-black/70" onClick={() => setIsModalOpen(false)} />

          {/* 内容 */}
          <div
            className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[90vw] h-[90vh] p-2 md:p-3 rounded-xl flex items-center justify-center"
            onClick={(e) => e.stopPropagation()}
          >
            {!imageLoaded && !loadError && (
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-white"></div>
              </div>
            )}

            {loadError ? (
              <a
                href={src}
                target="_blank"
                rel="noreferrer"
                className="text-white underline bg-black/40 rounded px-3 py-2"
              >
                查看图片
              </a>
            ) : (
              <img
                src={activeSrc}
                alt={alt}
                className={`w-full h-full object-contain transition-opacity duration-300 ${imageLoaded ? 'opacity-100' : 'opacity-0'}`}
                onLoad={() => {
                  setImageLoaded(true);
                  if (timeoutRef.current) { clearTimeout(timeoutRef.current); timeoutRef.current = null; }
                }}
                onError={() => {
                  if (!triedProxy) {
                    setActiveSrc(makeProxyUrl(src));
                    setTriedProxy(true);
                  } else {
                    setLoadError(true);
                    setImageLoaded(true);
                  }
                }}
              />
            )}

            {/* 关闭按钮 */}
            <button
              className="absolute top-3 right-3 text-white/90 hover:text-white"
              onClick={() => setIsModalOpen(false)}
              aria-label="close"
            >
              <X className="w-7 h-7" />
            </button>
          </div>
        </div>,
        document.body
      )}
    </>
  );
}
