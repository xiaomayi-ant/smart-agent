"use client";

import React, { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

type PdfViewerProps = {
  url: string;
  title?: string;
  className?: string;
  open?: boolean;
  onOpenChange?: (v: boolean) => void;
};

export function PdfViewer({ url, title, className = "", open, onOpenChange }: PdfViewerProps) {
  const [internalOpen, setInternalOpen] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const isOpen = open !== undefined ? open : internalOpen;
  const previewUrl = useMemo(() => {
    try { return `/api/preview/pdf?u=${encodeURIComponent(url)}`; } catch { return `/api/preview/pdf?u=${encodeURIComponent(url)}`; }
  }, [url]);

  const displayName = useMemo(() => {
    if (title && typeof title === 'string') return title;
    try {
      const u = new URL(url);
      const seg = decodeURIComponent(u.pathname.split('/').pop() || 'pdf');
      return seg || 'pdf';
    } catch {
      try { return decodeURIComponent(url.split('/').pop() || 'pdf'); } catch { return 'pdf'; }
    }
  }, [title, url]);

  useEffect(() => {
    if (!isOpen) {
      setLoaded(false);
      return;
    }
    const timer = setTimeout(() => {
      if (!loaded) {
        try { window.open(url, "_blank"); } catch {}
        if (onOpenChange) onOpenChange(false); else setInternalOpen(false);
      }
    }, 1500);
    return () => clearTimeout(timer);
  }, [isOpen, loaded, url, onOpenChange]);

  const handleClose = () => {
    if (onOpenChange) onOpenChange(false); else setInternalOpen(false);
  };

  return (
    <>
      {title ? (
        <div className={className} onClick={() => (onOpenChange ? onOpenChange(true) : setInternalOpen(true))}>
          {title}
        </div>
      ) : null}
      {isOpen && typeof document !== 'undefined'
        ? createPortal(
            <div className="fixed inset-0 z-[1000] bg-black/10 flex items-center justify-center p-4" onClick={handleClose}>
              <div className="relative w-[67.5vw] max-w-[990px] h-[82.5vh] max-h-[93.5vh] bg-white rounded-xl shadow-2xl overflow-hidden border border-white ring-1 ring-white/60 flex flex-col" onClick={(e) => e.stopPropagation()}>
                <div className="h-11 min-h-11 flex items-center justify-between px-4 border-b border-border/60 bg-white/95">
                  <div className="truncate text-sm font-medium" title={displayName}>{displayName}</div>
                  <button className="p-1 text-muted-foreground hover:text-foreground" aria-label="close" onClick={handleClose}>
                    <X className="w-4 h-4" />
                  </button>
                </div>
                <div className="flex-1 min-h-0">
                  <iframe
                    src={previewUrl}
                    className="w-full h-full"
                    onLoad={() => setLoaded(true)}
                    onError={() => {
                      try { window.open(url, "_blank"); } catch {}
                      handleClose();
                    }}
                  />
                </div>
              </div>
            </div>,
            document.body
          )
        : null}
    </>
  );
}

export default PdfViewer;


