import { ThreadState, Client } from "@langchain/langgraph-sdk";
import { LangChainMessage } from "@assistant-ui/react-langgraph";

const createClient = () => {
  const apiUrl =
    process.env["NEXT_PUBLIC_LANGGRAPH_API_URL"] ||
    new URL("/api", window.location.href).href;
  return new Client({
    apiUrl,
  });
};

export const createAssistant = async (graphId: string) => {
  const client = createClient();
  return client.assistants.create({ graphId });
};

export const createThread = async () => {
  const client = createClient();
  return client.threads.create();
};

export const getThreadState = async (
  threadId: string
): Promise<ThreadState<Record<string, any>>> => {
  const client = createClient();
  return client.threads.getState(threadId);
};

export const updateState = async (
  threadId: string,
  fields: {
    newState: Record<string, any>;
    asNode?: string;
  }
) => {
  const client = createClient();
  return client.threads.updateState(threadId, {
    values: fields.newState,
    asNode: fields.asNode!,
  });
};

export const sendMessage = async (params: {
  conversationId: string;
  threadId: string;
  messages: LangChainMessage[];
  signal?: AbortSignal;
}) => {
  console.log(`[chatApi] 发送消息到: /api/chat/stream`);
  console.log(`[chatApi] 会话: ${params.conversationId}, 线程: ${params.threadId}`);
  console.log(`[chatApi] 消息内容:`, params.messages);
  
  const response = await fetch(`/api/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      conversationId: params.conversationId,
      threadId: params.threadId,
      messages: params.messages,
    }),
    signal: params.signal,
  });

  // 如果非OK，不要直接抛错，返回一个只发出一次错误事件的异步生成器
  if (!response.ok) {
    const errMsg = `HTTP error ${response.status}`;
    const errorStream = (async function* () {
      try {
        yield { event: "error", data: { message: errMsg } } as any;
      } finally {
        // complete to allow UI to settle
        yield { event: "messages/complete", data: [] } as any;
      }
    })();
    return errorStream;
  }

  // 创建一个异步生成器来处理SSE流
  const stream = (async function* () {
    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error("No response body");
    }

    const decoder = new TextDecoder();
    let buffer = "";
    // 当 signal.abort 时，立即取消 reader，保证中止即时生效
    let abortListener: any | null = null;
    try {
      if (params.signal) {
        if (params.signal.aborted) {
          try { await reader.cancel(); } catch {}
          return; // 直接结束生成器
        }
        abortListener = async () => {
          try { await reader.cancel(); } catch {}
        };
        params.signal.addEventListener("abort", abortListener, { once: true } as any);
      }
    } catch {}

    try {
      while (true) {
        // 如果外部已经请求中断，停止读取
        if (params.signal?.aborted) {
          break;
        }
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // 逐块解析（以空行分隔的 SSE 事件块）
        let separatorIndex: number;
        // 兼容 \n\n 和 \r\n\r\n 两种分隔
        // 优先查找 \n\n，如未找到再查找 \r\n\r\n
        // 循环消费完整块
        while ((separatorIndex = buffer.indexOf("\n\n")) !== -1 || (separatorIndex = buffer.indexOf("\r\n\r\n")) !== -1) {
          const block = buffer.slice(0, separatorIndex);
          buffer = buffer.slice(separatorIndex + (buffer[separatorIndex] === "\r" ? 4 : 2));

          // 解析单个块
          const lines = block.split(/\r?\n/);
          let event: string | null = null;
          const dataLines: string[] = [];

          for (const line of lines) {
            if (line.startsWith("event:")) {
              event = line.slice(6).trim();
            } else if (line.startsWith("data:")) {
              dataLines.push(line.slice(5).trim());
            }
          }

          if (!event) {
            continue; // 没有事件名则跳过
          }

          const dataStr = dataLines.join("\n");
          if (!dataStr) {
            yield { event, data: [] };
            continue;
          }

          try {
            const parsedData = JSON.parse(dataStr);
            // 调试事件直接在前端控制台打印
            if (event === "debug") {
              try { console.debug(`[SSE DEBUG]`, parsedData); } catch {}
              continue;
            }
            yield { event, data: parsedData };
          } catch (e) {
            console.warn(`[chatApi] 解析SSE数据失败:`, dataStr, e);
          }
        }
      }
    } catch (e: any) {
      // 若因 AbortError 中断，优雅结束
      if (params.signal?.aborted) {
        yield { event: "messages/complete", data: [] } as any;
      } else {
        throw e;
      }
    } finally {
      try { reader.releaseLock(); } catch {}
      try { if (params.signal && abortListener) params.signal.removeEventListener("abort", abortListener as any); } catch {}
    }
  })();

  return stream;
};

export const visionStream = async (params: {
  file: File;
  question: string;
}) => {
  const formData = new FormData();
  formData.append("image", params.file);
  formData.append("question", params.question || "请描述这张图片");

  const response = await fetch(`/api/vision-qa`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }

  const stream = (async function* () {
    const reader = response.body?.getReader();
    if (!reader) throw new Error("No response body");
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let separatorIndex: number;
        while (
          (separatorIndex = buffer.indexOf("\n\n")) !== -1 ||
          (separatorIndex = buffer.indexOf("\r\n\r\n")) !== -1
        ) {
          const block = buffer.slice(0, separatorIndex);
          buffer = buffer.slice(separatorIndex + (buffer[separatorIndex] === "\r" ? 4 : 2));
          const lines = block.split(/\r?\n/);
          let event: string | null = null;
          const dataLines: string[] = [];
          for (const line of lines) {
            if (line.startsWith("event:")) event = line.slice(6).trim();
            else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
          }
          if (!event) event = "message"; // default for provider lines without explicit event
          const dataStr = dataLines.join("\n");
          if (!dataStr) {
            yield { event, data: [] };
            continue;
          }
          if (dataStr === "[DONE]") {
            yield { event: "done", data: null } as any;
            break;
          }
          try {
            const parsedData = JSON.parse(dataStr);
            yield { event, data: parsedData };
          } catch (e) {
            console.warn(`[chatApi] 解析SSE数据失败:`, dataStr, e);
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  })();

  return stream;
};

// 异步上传文件，立即返回文件指针
export const uploadAsync = async (file: File, threadId?: string): Promise<{
  fileId: string;
  url: string;
  signedUrl?: string;
  thumbUrl?: string;
  name: string;
  mime: string;
  size: number;
  status: string;
}> => {
  console.log(`[chatApi] 异步上传文件: ${file.name}`);
  
  // 优先：图片走后端签发的直传 PUT，绕过 Next 中转
  if (file.type.startsWith('image/')) {
    // 1) 申请预签名 PUT 与 GET（signedUrl）
    const presign = await fetch(`/api/oss/presign-upload`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename: file.name, contentType: file.type, category: 'images' })
    });
    if (!presign.ok) throw new Error(`Presign failed: ${presign.status}`);
    const { putUrl, signedUrl } = await presign.json();
    // 2) 直接 PUT 到 OSS（不经 Next）
    const putResp = await fetch(putUrl, { method: 'PUT', headers: { 'Content-Type': file.type }, body: file });
    if (!putResp.ok) throw new Error(`PUT failed: ${putResp.status}`);
    // 3) 构造返回（无 fileId，这里以 URL 直用；如需入库，可追加异步记录）
    return {
      fileId: `tmp_${Date.now()}`,
      url: signedUrl,
      signedUrl,
      thumbUrl: signedUrl,
      name: file.name,
      mime: file.type,
      size: file.size,
      status: 'ready',
    };
  }

  // 非图片仍走 Next 统一上传
  const fd = new FormData();
  fd.append('file', file);
  if (threadId) fd.append('threadId', threadId);
  const response = await fetch(`/api/upload?mode=async`, { method: 'POST', body: fd });
  if (!response.ok) throw new Error(`Upload failed: ${response.status}`);
  const result = await response.json();
  console.log(`[chatApi] 异步上传结果:`, result);
  return {
    fileId: result.fileId,
    url: result.url,
    name: result.name || file.name,
    mime: result.mime || file.type,
    size: result.size || file.size,
    status: result.status || 'processing',
  };
};

// 轮询文件处理状态
export const pollFileStatus = async (fileId: string): Promise<{
  status: 'processing' | 'ready' | 'failed';
  filename?: string;
  result?: any;
  error?: string;
}> => {
  console.log(`[chatApi] 查询文件状态: ${fileId}`);
  
  const response = await fetch(`/api/documents/status?fileId=${fileId}`);
  
  if (!response.ok) {
    throw new Error(`Status query failed: ${response.status}`);
  }
  
  const result = await response.json();
  console.log(`[chatApi] 文件状态:`, result);
  
  return {
    status: result.status,
    filename: result.filename,
    result: result.result,
    error: result.error
  };
};