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
  threadId: string;
  messages: LangChainMessage[];
}) => {
  const apiUrl = process.env["NEXT_PUBLIC_LANGGRAPH_API_URL"] || "http://localhost:3001/api";
  
  console.log(`[chatApi] 发送消息到: ${apiUrl}/threads/${params.threadId}/runs/stream`);
  console.log(`[chatApi] 消息内容:`, params.messages);
  
  const response = await fetch(`${apiUrl}/threads/${params.threadId}/runs/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      input: {
        messages: params.messages,
      },
    }),
  });

  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }

  // 创建一个异步生成器来处理SSE流
  const stream = (async function* () {
    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error("No response body");
    }

    const decoder = new TextDecoder();
    let buffer = "";

    try {
      while (true) {
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