import { NextRequest, NextResponse } from "next/server";

export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData();
    const file = formData.get("file") as File;
    const threadId = formData.get("threadId") as string;

    console.log(`[Upload API] 接收到文件上传请求`);
    console.log(`[Upload API] 文件信息:`, {
      name: file?.name,
      type: file?.type,
      size: file?.size,
      threadId
    });

    if (!file) {
      console.log(`[Upload API] 错误: 没有提供文件`);
      return NextResponse.json({ error: "No file provided" }, { status: 400 });
    }

    if (!threadId) {
      console.log(`[Upload API] 错误: 没有提供threadId`);
      return NextResponse.json({ error: "No threadId provided" }, { status: 400 });
    }

    // 验证文件类型
    const allowedTypes = ["text/plain", "application/pdf", "image/jpeg", "image/png"];
    console.log(`[Upload API] 文件类型: ${file.type}, 允许的类型: ${allowedTypes.join(", ")}`);
    
    if (!allowedTypes.includes(file.type)) {
      console.log(`[Upload API] 错误: 不支持的文件类型 ${file.type}`);
      return NextResponse.json({ error: `Unsupported file type: ${file.type}` }, { status: 400 });
    }

    // 验证文件大小 (10MB)
    const maxSize = 10 * 1024 * 1024;
    if (file.size > maxSize) {
      console.log(`[Upload API] 错误: 文件大小超过限制 ${file.size} > ${maxSize}`);
      return NextResponse.json({ error: "File size exceeds 10MB limit" }, { status: 400 });
    }

    // 生成唯一文件ID
    const fileId = `file_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
    
    // 模拟文件上传到存储服务
    // 在实际应用中，这里应该上传到云存储服务（如AWS S3、Google Cloud Storage等）
    const url = `https://example.com/uploads/${fileId}/${file.name}`;

    console.log(`[Upload API] 文件上传成功:`, { fileId, url, name: file.name });

    // 返回文件信息
    return NextResponse.json({
      fileId,
      url,
      name: file.name,
      contentType: file.type,
      size: file.size,
    });

  } catch (error: any) {
    console.error("[Upload API] 上传错误:", error);
    return NextResponse.json(
      { error: "Upload failed", details: error.message },
      { status: 500 }
    );
  }
}

export async function OPTIONS() {
  return new NextResponse(null, {
    status: 204,
    headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    },
  });
} 