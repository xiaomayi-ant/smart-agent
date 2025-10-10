"use client";

import React, { useState } from "react";
import { Download } from "lucide-react";
import PdfViewer from "@/components/ui/pdf-viewer";

type AnyProps = Record<string, any>;

function formatBytes(bytes?: number): string | undefined {
  if (!bytes || !Number.isFinite(bytes)) return undefined;
  const units = ["B", "KB", "MB", "GB"]; let i = 0; let n = bytes;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(n < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
}

function extractBasic(props: AnyProps): { url?: string; name: string; mime?: string; size?: number; } {
  try {
    const url = typeof props?.url === "string" ? props.url
      : typeof props?.href === "string" ? props.href
      : typeof props?.source === "string" ? props.source
      : undefined;
    const name = typeof props?.name === "string" ? props.name
      : typeof props?.filename === "string" ? props.filename
      : (url ? decodeURIComponent(url.split("/").pop() || "file") : "file");
    const mime = typeof props?.mime === "string" ? props.mime
      : typeof props?.contentType === "string" ? props.contentType
      : undefined;
    const size = typeof props?.size === "number" ? props.size
      : (typeof props?.bytes === "number" ? props.bytes : undefined);
    return { url, name, mime, size };
  } catch { return { url: undefined, name: "file" }; }
}

function isTableFile(name: string, mime?: string): boolean {
  const lower = (name || "").toLowerCase();
  if (mime && /(^text\/csv$)|spreadsheet|excel/i.test(mime)) return true;
  return /\.csv(\?.*)?$/.test(lower) || /\.xlsx(\?.*)?$/.test(lower) || /\.xls(\?.*)?$/.test(lower);
}

function isPdf(name: string, mime?: string): boolean {
  const lower = (name || "").toLowerCase();
  if (mime && /application\/pdf/i.test(mime)) return true;
  return /\.pdf(\?.*)?$/i.test(lower);
}

function tableLabel(name: string, mime?: string): string {
  const lower = (name || "").toLowerCase();
  if (/\.xlsx(\?.*)?$/i.test(lower)) return "Excel/xlsx";
  if (/\.xls(\?.*)?$/i.test(lower)) return "Excel/xls";
  if (/\.csv(\?.*)?$/i.test(lower)) return "CSV";
  if (mime && /spreadsheet|excel/i.test(mime)) return "Excel";
  return "表格";
}

function tableBadgeText(name: string, mime?: string): string {
  const lower = (name || "").toLowerCase();
  if (/\.csv(\?.*)?$/i.test(lower)) return "CSV";
  if (/\.xlsx(\?.*)?$/i.test(lower)) return "XLSX";
  if (/\.xls(\?.*)?$/i.test(lower)) return "XLS";
  if (mime && /csv/i.test(mime)) return "CSV";
  if (mime && /xlsx/i.test(mime)) return "XLSX";
  if (mime && /excel|spreadsheet/i.test(mime)) return "XLS";
  return "TABLE";
}

export function FileBubble(props: AnyProps & { alignRight?: boolean }) {
  const { alignRight } = props;
  const { url, name, mime, size } = extractBasic(props);
  const isTable = isTableFile(name, mime);
  const pdf = isPdf(name, mime);
  const [openPdf, setOpenPdf] = useState(false);

  const containerCls = `${alignRight ? "ml-auto" : ""} inline-flex items-start gap-2 rounded-lg border border-border bg-transparent px-3 py-2 text-sm max-w-[80%]`;

  const openInNew = () => { try { if (url) window.open(url, "_blank"); } catch {} };
  const download = (e?: React.MouseEvent) => { try { if (e) e.stopPropagation(); if (!url) return; const a = document.createElement('a'); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove(); } catch {} };

  // 表格：仅名称+类型，右上角下载按钮；整卡点击新标签
  if (isTable) {
    return (
      <div className={containerCls + " cursor-pointer"} style={{ width: 320 }} onClick={openInNew}>
        <div className="inline-flex h-8 w-10 items-center justify-center rounded bg-[#78C841] text-foreground font-semibold mr-2 text-[11px]">
          {tableBadgeText(name, mime)}
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate max-w-[220px]">{name}</div>
          <div className="text-xs text-muted-foreground">{tableLabel(name, mime)}</div>
        </div>
        <button className="text-muted-foreground hover:text-foreground p-1" aria-label="download" onClick={download}>
          <Download className="w-4 h-4" />
        </button>
      </div>
    );
  }

  // PDF：点击打开小窗口
  if (pdf) {
    return (
      <>
        <div className={containerCls + " cursor-pointer"} style={{ width: 320 }} onClick={() => setOpenPdf(true)}>
          <div className="inline-flex h-8 w-10 items-center justify-center rounded bg-[#FF894F] text-foreground font-semibold mr-2 text-[11px]">PDF</div>
          <div className="min-w-0 flex-1">
            <div className="truncate max-w-[260px]">{name}</div>
            <div className="text-xs text-muted-foreground">{mime || "PDF"}{typeof size === "number" ? ` · ${formatBytes(size)}` : ""}</div>
          </div>
        </div>
        {url ? <PdfViewer url={url} open={openPdf} onOpenChange={setOpenPdf} /> : null}
      </>
    );
  }

  // 其他：整卡点击新标签
  return (
    <div className={containerCls + " cursor-pointer"} style={{ width: 320 }} onClick={openInNew}>
      <div className="inline-flex h-8 w-10 items-center justify-center rounded bg-[#77BEF0] text-foreground font-semibold mr-2 text-[11px]">FILE</div>
      <div className="min-w-0 flex-1">
        <div className="truncate max-w-[260px]">{name}</div>
        <div className="text-xs text-muted-foreground">{mime || "文件"}{typeof size === "number" ? ` · ${formatBytes(size)}` : ""}</div>
      </div>
    </div>
  );
}

export default FileBubble;


