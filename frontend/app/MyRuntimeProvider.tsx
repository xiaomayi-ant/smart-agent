"use client";

import { useRef, useState } from "react";
import { AssistantRuntimeProvider, AttachmentAdapter, PendingAttachment, CompleteAttachment } from "@assistant-ui/react";
import { useLangGraphRuntime, LangChainMessage } from "@assistant-ui/react-langgraph";
import { createThread, sendMessage } from "@/lib/chatApi";

// 定义本地附件状态接口
interface LocalAttachment {
  id: string;
  type: "file" | "image" | "document";
  name: string;
  contentType: string;
  size: number;
  file: File;
  fileId?: string;
  url?: string;
  status: any; // 使用any来避免复杂的类型匹配
  createdAt: number;
  deleted?: boolean;
  fileContent?: string; // 新增：保存文件内容
}

export function MyRuntimeProvider({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const threadIdRef = useRef<string | undefined>(undefined);
  const [attachments, setAttachments] = useState<LocalAttachment[]>([]); // 本地状态管理附件
  const attachmentsRef = useRef<LocalAttachment[]>([]); // 使用ref来保存最新状态
  const [isUploading, setIsUploading] = useState(false); // 添加上传状态标志
  const isStreamingRef = useRef(false); // 添加流式处理状态标志

  // 状态追踪函数
  const logStateChange = (action: string, data: any) => {
    console.log(`[STATE] ${action}:`, data);
  };

  // 更新ref当attachments状态变化时
  const updateAttachmentsRef = (newAttachments: LocalAttachment[]) => {
    attachmentsRef.current = newAttachments;
    console.log(`[REF] 更新附件引用，当前数量: ${newAttachments.length}`);
  };

  const attachmentAdapter: AttachmentAdapter = {
    accept: "text/plain,application/pdf,image/*", // 限制安全类型

    // add 方法：预验证文件，生成 pending 元数据
    async add({ file }: { file: File }): Promise<PendingAttachment> {
      console.log(`[ADD] 开始添加文件: ${file.name}`);
      
      const allowedTypes = ["text/plain", "application/pdf", "image/jpeg", "image/png"];
      if (!allowedTypes.includes(file.type)) {
        throw new Error(`不支持的文件类型: ${file.type}`);
      }
      const maxSize = 10 * 1024 * 1024; // 10MB 上限
      if (file.size > maxSize) {
        throw new Error("文件大小超过 10MB");
      }
      
      const id = `file_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
      const attachment: PendingAttachment = {
        id,
        type: "file",
        name: file.name,
        contentType: file.type,
        file,
        status: { type: "requires-action", reason: "composer-send" },
      };
      
      // 创建本地附件状态
      const localAttachment: LocalAttachment = {
        ...attachment,
        size: file.size,
        createdAt: Date.now(),
      };
      
      setAttachments((prev) => {
        const newState = [...prev, localAttachment];
        logStateChange("添加文件", { id, name: file.name, totalCount: newState.length });
        updateAttachmentsRef(newState); // 更新ref
        return newState;
      });
      
      console.log(`[ADD] 文件添加成功: ${file.name}, ID: ${id}`);
      return attachment;
    },

    // send 方法：只负责文件上传，不发送消息
    async send(attachment: PendingAttachment): Promise<CompleteAttachment> {
      console.log(`[SEND] 开始上传文件: ${attachment.name}`);
      
      // 设置上传状态
      setIsUploading(true);
      
      // 确保threadId存在
      if (!threadIdRef.current) {
        console.log(`[SEND] 创建新线程`);
        const { thread_id } = await createThread();
        threadIdRef.current = thread_id;
      }
      
      try {
        // 更新状态为 uploading，支持进度反馈
        setAttachments((prev) => {
          const newState = prev.map((a) => {
            if (a.id === attachment.id) {
              const updated = { ...a, status: { type: "uploading", progress: 0 } };
              logStateChange("开始上传", { id: a.id, name: a.name, progress: 0 });
              return updated;
            }
            return a;
          });
          updateAttachmentsRef(newState); // 更新ref
          return newState;
        });

        // 模拟进度更新
        const progressInterval = setInterval(() => {
          setAttachments((prev) => {
            const newState = prev.map((a) => {
              if (a.id === attachment.id && a.status.type === "uploading") {
                const newProgress = Math.min((a.status.progress || 0) + 25, 100);
                const updated = { ...a, status: { type: "uploading", progress: newProgress } };
                logStateChange("上传进度", { id: a.id, name: a.name, progress: newProgress });
                return updated;
              }
              return a;
            });
            updateAttachmentsRef(newState); // 更新ref
            return newState;
          });
        }, 300);

        // 使用真实API上传文件
        const formData = new FormData();
        formData.append("file", attachment.file);
        formData.append("threadId", threadIdRef.current || "");
        
        console.log(`[SEND] 准备上传文件:`, {
          name: attachment.file.name,
          type: attachment.file.type,
          size: attachment.file.size,
          threadId: threadIdRef.current
        });
        
        const response = await fetch("/api/upload", {
          method: "POST",
          body: formData,
        });
        
        if (!response.ok) {
          throw new Error(`上传失败: ${response.statusText}`);
        }
        
        const uploadResult = await response.json();
        clearInterval(progressInterval);

        console.log(`[SEND] 文件上传成功:`, uploadResult);

        // 读取文件内容（用于后续消息构造）
        let fileContent = "";
        try {
          if (attachment.contentType === "text/plain") {
            fileContent = await attachment.file.text();
            console.log(`[SEND] 读取文件内容成功，长度: ${fileContent.length}`);
          } else {
            fileContent = `[${attachment.contentType} 文件内容]`;
            console.log(`[SEND] 非文本文件，使用占位符`);
          }
        } catch (error) {
          console.warn(`[SEND] 读取文件内容失败:`, error);
          fileContent = `[无法读取文件内容: ${attachment.name}]`;
        }

        const completeAttachment: CompleteAttachment = {
          id: attachment.id,
          type: "file",
          name: attachment.name,
          contentType: attachment.contentType,
          status: { type: "complete" },
          content: [
            { type: "text", text: `File: ${attachment.name} (${attachment.contentType})` },
          ],
        };

        // 更新本地状态，保存文件内容和上传结果
        setAttachments((prev) => {
          const newState = prev.map((a) => {
            if (a.id === attachment.id) {
              const updated = { 
                ...a, 
                fileId: uploadResult.fileId, 
                url: uploadResult.url, 
                status: { type: "complete" },
                fileContent: fileContent // 保存文件内容供后续使用
              };
              logStateChange("上传完成", { id: a.id, name: a.name, fileId: uploadResult.fileId });
              return updated;
            }
            return a;
          });
          updateAttachmentsRef(newState); // 更新ref
          return newState;
        });
        
        console.log(`[SEND] 文件上传完成: ${attachment.name}`);
        return completeAttachment;
      } catch (error: any) {
        console.error(`[SEND] 文件上传失败: ${attachment.name}`, error);
        
        setAttachments((prev) => {
          const newState = prev.map((a) => {
            if (a.id === attachment.id) {
              const updated = { ...a, status: { type: "requires-action", reason: error.message } };
              logStateChange("上传失败", { id: a.id, name: a.name, error: error.message });
              return updated;
            }
            return a;
          });
          updateAttachmentsRef(newState); // 更新ref
          return newState;
        });
        throw error;
      } finally {
        // 清除上传状态
        setIsUploading(false);
      }
    },

    // remove 方法：通知后端删除，更新状态，处理删除矛盾
    async remove(attachment: CompleteAttachment): Promise<void> {
      console.log(`[REMOVE] 开始删除文件: ${attachment.name}`);
      
      try {
        const localAttachment = attachments.find(a => a.id === attachment.id);
        const fileId = localAttachment?.fileId || attachment.id;
        const threadId = threadIdRef.current || "";
        
        console.log(`[REMOVE] 删除参数:`, { fileId, threadId, hasThreadId: !!threadId });
        
        // 使用真实API删除文件
        const response = await fetch(`/api/files/${fileId}`, {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ threadId }),
        });
        
        if (!response.ok) {
          console.warn(`[REMOVE] 删除文件API返回错误: ${response.status}`);
          // 不抛出错误，继续执行本地状态清理
        }
        
        // 直接更新本地状态，移除对不存在端点的调用
        setAttachments((prev) => {
          const newState = prev.filter((a) => a.id !== attachment.id);
          updateAttachmentsRef(newState);
          logStateChange("删除文件", { id: attachment.id, name: attachment.name, remainingCount: newState.length });
          return newState;
        });
        
        console.log(`[REMOVE] 文件删除完成: ${attachment.name}`);
      } catch (error) {
        console.error(`[REMOVE] 文件删除失败: ${attachment.name}`, error);
        
        // 即使删除失败，也要清理本地状态
        setAttachments((prev) => {
          const newState = prev.filter((a) => a.id !== attachment.id);
          updateAttachmentsRef(newState);
          return newState;
        });
        
        // 不抛出错误，避免界面崩溃
        console.log(`[REMOVE] 已清理本地状态，忽略删除错误`);
      }
    },
  };

  const runtime = useLangGraphRuntime({
    threadId: threadIdRef.current,
    stream: async (messages: LangChainMessage[]) => {
      // 防止重复调用
      if (isStreamingRef.current) {
        console.log(`[STREAM] 检测到重复调用，跳过`);
        // 返回一个空的异步生成器
        return (async function* () {
          yield { event: "error", data: { error: "重复调用被跳过" } };
        })();
      }
      
      isStreamingRef.current = true;
      console.log(`[STREAM] 开始处理消息，消息数量: ${messages.length}`);
      
      try {
        if (!threadIdRef.current) {
          const { thread_id } = await createThread();
          threadIdRef.current = thread_id;
        }

        // 如果有文件正在上传，等待上传完成
        if (isUploading) {
          console.log(`[STREAM] 检测到文件正在上传，等待完成...`);
          let waitCount = 0;
          while (isUploading && waitCount < 50) { // 最多等待5秒
            await new Promise(resolve => setTimeout(resolve, 100));
            waitCount++;
          }
          console.log(`[STREAM] 等待上传完成，等待次数: ${waitCount}`);
        }

        // 处理 langchain/langgraph-sdk的流式响应转换为@assistant-ui/react-langgraph期望的格式
        const convertToLangGraphFormat = async function* (streamResponse: any) {
          try {
            let hasYieldedContent = false;
            let chunkCount = 0;
            let accumulatedContent = ""; // 累积Python后端的内容
            let currentMessageId = `msg_${Date.now()}`; // 当前消息ID
            console.log(`[STREAM] 开始处理流式响应...`);
            
            for await (const chunk of streamResponse) {
              chunkCount++;
              console.log(`[STREAM] 处理chunk ${chunkCount}:`, chunk);
              
              // 修改：处理新事件类型，并映射到前端期望的 'messages/partial' 和 'messages/complete'
              if (chunk && typeof chunk === 'object') {
                console.log(`[STREAM] 处理事件类型: ${chunk.event}`);
                
                // 处理Python后端发送的partial_ai事件（与TypeScript后端一致）
                if (chunk.event === 'partial_ai' && chunk.data && Array.isArray(chunk.data)) {
                  hasYieldedContent = true;
                  
                  // 修改：Python后端发送的是完整内容，直接使用
                  if (chunk.data.length > 0 && chunk.data[0].content) {
                    // 使用后端发送的完整内容
                    accumulatedContent = chunk.data[0].content;
                    
                    // 使用后端提供的消息ID，如果没有则使用默认ID
                    const messageId = chunk.data[0].id || currentMessageId;
                    
                    // 确保消息ID一致，这样Assistant UI就能正确更新现有消息
                    const messagesWithId = [{
                      id: messageId,
                      type: 'ai',
                      content: accumulatedContent // 发送完整内容
                    }];
                    
                    console.log(`[STREAM] 发送partial_ai事件，消息ID: ${messageId}, 内容长度: ${accumulatedContent.length}`);
                    yield { event: 'messages/partial', data: messagesWithId };
                  }
                } else if (chunk.event === 'tool_result' && chunk.data && Array.isArray(chunk.data)) {
                  // 映射 tool_result 到 messages/partial，并转换为 ai 类型
                  hasYieldedContent = true;
                  const toolMessages = chunk.data.map((msg: any, index: number) => {
                    if (msg.type === 'tool') {
                      // 将工具结果转换为AI消息
                      console.log(`[STREAM] 转换工具消息为AI消息:`, msg);
                      return {
                        id: msg.id || `tool_${Date.now()}_${index}`,
                        type: 'ai',  // 转换为ai类型
                        content: msg.content
                      };
                    }
                    return {
                      ...msg,
                      id: msg.id || `tool_${Date.now()}_${index}`
                    };
                  });
                  yield { event: 'messages/partial', data: toolMessages };
                } else if (chunk.event === 'message' && chunk.data) {
                  // 处理OpenAI格式的聊天完成响应（兼容性）
                  const data = chunk.data;
                  if (data.choices && data.choices.length > 0) {
                    const choice = data.choices[0];
                    if (choice.delta && choice.delta.content) {
                      // 有内容更新，累积内容并发送完整内容
                      hasYieldedContent = true;
                      const deltaContent = choice.delta.content;
                      accumulatedContent += deltaContent;
                      yield { event: 'messages/partial', data: [{ 
                        id: currentMessageId,
                        type: 'ai', 
                        content: accumulatedContent  // 发送累积内容，不是增量内容
                      }] };
                    } else if (choice.finish_reason === 'stop') {
                      // 响应完成
                      yield { event: 'messages/complete', data: [] };
                    }
                  }
                } else if (chunk.event === 'complete') {
                  // 映射 complete 到 messages/complete
                  yield { event: 'messages/complete', data: [] };
                } else if (chunk.event === 'on_tool_end') {
                  // 处理工具执行完成事件
                  hasYieldedContent = true;
                  yield { event: 'messages/partial', data: [{ 
                    id: `tool_end_${Date.now()}`,
                    type: 'ai', 
                    content: chunk.data?.message || '工具执行完成'
                  }] };
                } else if (chunk.event === 'on_chain_end') {
                  // 处理链事件
                  console.log(`[STREAM] 处理链事件:`, chunk);
                  if (chunk.data && chunk.data.output) {
                    hasYieldedContent = true;
                    yield { event: 'messages/partial', data: [{ 
                      id: `msg_${Date.now()}_tool`,
                      type: 'ai', 
                      content: typeof chunk.data.output === "string" ? chunk.data.output : JSON.stringify(chunk.data.output)
                    }] };
                  }
                } else if (chunk.event && chunk.data) {
                  // 其他事件，直接传递
                  yield chunk;
                } else {
                  console.warn(`[STREAM] 未知chunk格式:`, chunk);
                }
              } else {
                console.warn(`[STREAM] 无效chunk:`, chunk);
              }
            }
            
            console.log(`[STREAM] 流式响应处理完成，总chunk数: ${chunkCount}, 是否有内容: ${hasYieldedContent}`);
            
            // 如果没有收到任何内容，发送一个默认响应
            if (!hasYieldedContent) {
              console.log(`[STREAM] 没有收到内容，发送默认响应`);
              yield { event: 'messages/partial', data: [{ 
                id: `msg_${Date.now()}_default`,
                type: 'ai', 
                content: '正在处理您的请求...' 
              }] };
              yield { event: 'messages/complete', data: [] };
            }
          } catch (error) {
            console.error(`[STREAM] 流式响应处理错误:`, error);
            yield { event: 'messages/partial', data: [{ type: 'ai', content: '处理过程中出现错误，请重试。' }] };
            yield { event: 'messages/complete', data: [] };
          }
        };

        // 检查是否有附件需要处理，使用 attachmentsRef.current 获取最新状态
        const completedAttachments = attachmentsRef.current.filter(a => a.status.type === "complete" && a.fileContent);
        
        console.log(`[STREAM] 当前附件状态:`, attachmentsRef.current.map(a => ({
          id: a.id,
          name: a.name,
          status: a.status.type,
          hasContent: !!a.fileContent,
          contentLength: a.fileContent?.length || 0
        })));
        
        if (completedAttachments.length > 0) {
          console.log(`[STREAM] 发现 ${completedAttachments.length} 个已完成的附件，构造多模态消息`);
          console.log(`[STREAM] 附件详情:`, completedAttachments.map(a => ({
            name: a.name,
            contentLength: a.fileContent?.length || 0,
            contentPreview: a.fileContent?.substring(0, 100) + '...'
          })));
          
          // 构造包含文件内容的多模态消息
          const enhancedMessages = messages.map((msg, index) => {
            if (index === messages.length - 1 && msg.type === "human") {
              console.log(`[STREAM] 处理最后一个用户消息:`, msg);
              
              // 最后一个用户消息，添加文件内容
              const fileContents = completedAttachments.map(attachment => ({
                type: "text" as const,
                text: `文件信息: ${attachment.name} (${attachment.contentType}, ${attachment.url})\n文件内容:\n${attachment.fileContent}`
              }));
              
              const enhancedMessage = {
                ...msg,
                content: [
                  ...(Array.isArray(msg.content) ? msg.content : [{ type: "text" as const, text: msg.content }]),
                  ...fileContents
                ]
              };
              
              console.log(`[STREAM] 增强后的消息:`, enhancedMessage);
              console.log(`[STREAM] 消息内容部分数量:`, enhancedMessage.content.length);
              
              return enhancedMessage;
            }
            return msg;
          });
          
          console.log(`[STREAM] 发送增强消息，包含 ${completedAttachments.length} 个文件`);
          const streamResponse = await sendMessage({
            threadId: threadIdRef.current,
            messages: enhancedMessages,
          });
          
          // 延迟清除附件，在流式处理完成后再清除
          setTimeout(() => {
            setAttachments((prev) => {
              const newState = prev.filter(a => !completedAttachments.some(ca => ca.id === a.id));
              updateAttachmentsRef(newState);
              console.log(`[STREAM] 延迟清除附件，剩余数量: ${newState.length}`);
              return newState;
            });
          }, 1000); // 延迟1秒清除
          
          return convertToLangGraphFormat(streamResponse);
        } else {
          // 没有附件，正常发送消息
          console.log(`[STREAM] 发送普通消息`);
          const streamResponse = await sendMessage({
            threadId: threadIdRef.current,
            messages,
          });
          
          return convertToLangGraphFormat(streamResponse);
        }
      } catch (error) {
        console.error(`[STREAM] 处理错误:`, error);
        throw error;
      } finally {
        isStreamingRef.current = false;
        console.log(`[STREAM] 处理完成`);
      }
    },
    adapters: { attachments: attachmentAdapter },
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      {children}
    </AssistantRuntimeProvider>
  );
}