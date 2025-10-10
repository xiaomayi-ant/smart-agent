/**
 * 消息分析器 - 判断是否需要视觉分析
 */

export interface MessagePart {
  type: string;
  text?: string;
  image_url?: {
    url: string;
    detail?: string;
  };
  image?: string;
}

export interface LangChainMessage {
  role: string;
  content: string | MessagePart[];
}

/**
 * 检查消息是否包含图片
 */
export function hasImages(message: LangChainMessage): boolean {
  if (typeof message.content === 'string') {
    return false;
  }
  
  if (Array.isArray(message.content)) {
    return message.content.some(part =>
      (part.type === 'image_url' && !!part.image_url?.url) || (part.type === 'image' && typeof part.image === 'string')
    );
  }
  
  return false;
}

/**
 * 提取消息中的图片
 */
export function extractImages(message: LangChainMessage): string[] {
  if (!hasImages(message)) {
    return [];
  }
  
  const content = message.content as MessagePart[];
  return content
    .filter(part => (part.type === 'image_url' && part.image_url?.url) || (part.type === 'image' && typeof part.image === 'string'))
    .map(part => (part.type === 'image' ? (part.image as string) : (part.image_url!.url)));
}

/**
 * 提取消息中的文本
 */
export function extractText(message: LangChainMessage): string {
  if (typeof message.content === 'string') {
    return message.content;
  }
  
  if (Array.isArray(message.content)) {
    const textParts = message.content
      .filter(part => part.type === 'text' && part.text)
      .map(part => part.text!);
    return textParts.join(' ');
  }
  
  return '';
}

/**
 * 智能判断是否需要视觉分析
 * 这里先用简单规则，后续可以用 LLM 判断
 */
export function shouldUseVision(messages: LangChainMessage[]): boolean {
  // 检查最后一条用户消息是否包含图片
  const lastUserMessage = [...messages].reverse().find(msg => msg.role === 'user');
  
  if (!lastUserMessage) {
    return false;
  }
  
  return hasImages(lastUserMessage);
}

/**
 * 为视觉分析准备消息
 */
export function prepareVisionMessage(message: LangChainMessage): {
  question: string;
  images: string[];
} {
  return {
    question: extractText(message) || "请描述这张图片",
    images: extractImages(message)
  };
}
