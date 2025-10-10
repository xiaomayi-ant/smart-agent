import { NextRequest, NextResponse } from "next/server";
import { uploadBufferToOss, buildAudioObjectKey } from "@/lib/oss";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function transcribeWithGroq(fileBuf: Buffer, mime: string, filename: string): Promise<string | null> {
  try {
    const key = process.env.GROQ_API_KEY;
    if (!key) return null;
    const form = new FormData();
    const blob = new Blob([fileBuf], { type: mime || "audio/webm" });
    form.append("file", blob, filename || `recording.webm`);
    form.append("model", "whisper-large-v3");
    const resp = await fetch("https://api.groq.com/openai/v1/audio/transcriptions", {
      method: "POST",
      headers: { Authorization: `Bearer ${key}` },
      body: form,
    });
    if (!resp.ok) return null;
    const data = await resp.json();
    const text: string | undefined = data?.text ?? data?.segments?.map((s: any) => s?.text).join("");
    return (text && String(text)) || "";
  } catch {
    return null;
  }
}

async function dashscopeSubmitAsyncJob(ossUrl: string, model: string, langHints?: string[]): Promise<string | null> {
  try {
    const key = process.env.DASHSCOPE_API_KEY;
    const endpoint = process.env.DASHSCOPE_ASR_URL || "https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription";
    if (!key) return null;
    try { console.log(`[ASR] submit -> endpoint: ${endpoint}, model: ${model}, url: ${ossUrl}`); } catch {}
    const resp = await fetch(endpoint, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${key}`,
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
      },
      body: JSON.stringify({
        model,
        input: { file_urls: [ossUrl] },
        parameters: langHints && langHints.length > 0 ? { language_hints: langHints } : undefined,
      }),
    });
    if (!resp.ok) {
      try { console.warn(`[ASR] submit failed -> status: ${resp.status}`); } catch {}
      try { const t = await resp.text(); console.warn(`[ASR] submit error body:`, t); } catch {}
      return null;
    }
    const data: any = await resp.json();
    const taskId = data?.output?.task_id || data?.task_id || data?.id;
    try { console.log(`[ASR] submit ok -> taskId: ${taskId}`); } catch {}
    return taskId ? String(taskId) : null;
  } catch {
    return null;
  }
}

async function dashscopePollTask(taskId: string, timeoutMs = 60000, intervalMs = 1000): Promise<any | null> {
  const key = process.env.DASHSCOPE_API_KEY;
  const base = process.env.DASHSCOPE_TASKS_URL || "https://dashscope.aliyuncs.com/api/v1/tasks";
  if (!key) return null;
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const url = `${base.replace(/\/$/, "")}/${encodeURIComponent(taskId)}`;
    const r = await fetch(url, { headers: { Authorization: `Bearer ${key}` } });
    if (r.ok) {
      const data: any = await r.json();
      const status = data?.output?.task_status || data?.task_status || data?.status;
      try { console.log(`[ASR] poll -> status: ${status}`); } catch {}
      if (status && ["SUCCEEDED", "succeeded", "SUCCESS", "COMPLETED"].includes(String(status).toUpperCase())) {
        return data;
      }
      if (status && ["FAILED", "ERROR"].includes(String(status).toUpperCase())) {
        try { console.warn(`[ASR] poll failed payload:`, data); } catch {}
        return data;
      }
    }
    await new Promise((res) => setTimeout(res, intervalMs));
  }
  return null;
}

async function dashscopeFetchTranscriptionTextFromUrl(url: string): Promise<string | null> {
  try {
    const r = await fetch(url);
    if (!r.ok) {
      try { console.warn(`[ASR] fetch transcript failed -> ${r.status}`); } catch {}
      return null;
    }
    const j: any = await r.json();
    const text =
      j?.result?.text ||
      j?.text ||
      j?.output?.text ||
      (Array.isArray(j?.result?.results) && j.result.results[0]?.text) ||
      (Array.isArray(j?.results) && j.results[0]?.text) ||
      (Array.isArray(j?.transcripts) && j.transcripts[0]) ||
      (Array.isArray(j?.nbest) && j.nbest[0]?.sentence) ||
      null;
    return text ? String(text) : null;
  } catch {
    return null;
  }
}

async function transcribeWithOpenAI(fileBuf: Buffer, mime: string, filename: string): Promise<string | null> {
  try {
    const key = process.env.OPENAI_API_KEY;
    if (!key) return null;
    const form = new FormData();
    const blob = new Blob([fileBuf], { type: mime || "audio/webm" });
    form.append("file", blob, filename || `recording.webm`);
    form.append("model", "whisper-1");
    const resp = await fetch("https://api.openai.com/v1/audio/transcriptions", {
      method: "POST",
      headers: { Authorization: `Bearer ${key}` },
      body: form,
    });
    if (!resp.ok) return null;
    const data = await resp.json();
    const text: string | undefined = data?.text ?? data?.segments?.map((s: any) => s?.text).join("");
    return (text && String(text)) || "";
  } catch {
    return null;
  }
}

export async function POST(req: NextRequest) {
  try {
    const form = await req.formData();
    const file = form.get("file") as File | null;
    if (!file) {
      return NextResponse.json({ error: "no_file" }, { status: 400 });
    }

    const arrayBuffer = await file.arrayBuffer();
    const buffer = Buffer.from(arrayBuffer);
    const mime = (file as any)?.type || "audio/webm";
    const filename = (file as any)?.name || `recording-${Date.now()}.webm`;

    // 1) 上传到 OSS，获取可公开访问的 URL
    let ossUrl: string | null = null;
    try {
      const key = buildAudioObjectKey(filename);
      const out = await uploadBufferToOss({ buffer, key, mime });
      ossUrl = out.url;
      try { console.log(`[ASR] uploaded to OSS -> key: ${key}, url: ${ossUrl}`); } catch {}
    } catch {}

    // 2) DashScope 异步 ASR（优先）
    const dashModel = process.env.DASHSCOPE_ASR_MODEL || process.env.QWEN_ASR_MODEL || "paraformer-v2";
    let text: string | null = null;
    if (ossUrl && process.env.DASHSCOPE_API_KEY) {
      const taskId = await dashscopeSubmitAsyncJob(ossUrl, dashModel, ["zh"]);
      if (taskId) {
        const task = await dashscopePollTask(taskId, 60000, 1000);
        const transcriptionUrl = task?.output?.task_result?.transcription_url || task?.transcription_url || task?.output?.transcription_url;
        try { console.log(`[ASR] task done -> transcription_url: ${transcriptionUrl || 'n/a'}`); } catch {}
        if (transcriptionUrl) {
          text = await dashscopeFetchTranscriptionTextFromUrl(String(transcriptionUrl));
        }
      }
    }

    // 3) 兜底：Groq → OpenAI → demo
    if (text == null) text = await transcribeWithGroq(buffer, mime, filename);
    if (text == null) text = await transcribeWithOpenAI(buffer, mime, filename);
    if (text == null) text = "[demo] 这是转写结果";

    return NextResponse.json({
      text,
      model:
        process.env.DASHSCOPE_API_KEY
          ? `${dashModel}@dashscope`
          : process.env.GROQ_API_KEY
          ? "whisper-large-v3@groq"
          : process.env.OPENAI_API_KEY
          ? "whisper-1@openai"
          : "demo",
      url: ossUrl || undefined,
    });
  } catch (e: any) {
    return NextResponse.json({ error: "transcribe_failed", details: e?.message || String(e) }, { status: 500 });
  }
}


