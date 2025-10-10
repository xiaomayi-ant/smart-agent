import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";
import { verifySession } from "@/lib/jwt";
import { prisma } from "@/lib/db";
import { withAuthHeaders } from "@/lib/withAuthHeaders";
import { uploadBufferToOss, buildAudioObjectKey, buildObjectKey } from "@/lib/oss";

export const runtime = "nodejs";

export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData();
    const file = formData.get("file") as File;
    const threadId = formData.get("threadId") as string;
    const jar: any = await (cookies() as unknown as Promise<ReturnType<typeof cookies>>);
    const sid = jar?.get?.("sid")?.value;
    const userId = sid ? await verifySession(sid) : null;
    const bucket = process.env.ALI_OSS_BUCKET || "";

    async function recordFile(params: {
      fileId: string;
      kind: string;
      key: string;
      etag?: string;
      mime: string;
      sizeBytes: number;
      status: string;
    }) {
      try {
        if (!userId || !bucket) return; // 无用户上下文或无 bucket 时跳过入库
        await prisma.$executeRaw`select set_config('app.user_id', ${userId}, true)`;
        await prisma.file.create({
          data: {
            id: params.fileId,
            user_id: userId,
            kind: params.kind,
            bucket,
            object_key: params.key,
            etag: params.etag || null,
            sha256: null,
            size_bytes: BigInt(params.sizeBytes),
            mime: params.mime || "application/octet-stream",
            status: params.status,
            meta: null,
          },
        });
      } catch (e) {
        console.warn("[Upload API] 记录 File 入库失败(忽略不中断):", e);
      }
    }

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

    // threadId 改为可选：若传则透传给后端/用于后续关联；未传不阻断上传
    if (!threadId) {
      console.log(`[Upload API] 提示: 未提供 threadId（允许，无阻断）`);
    }

    // 放宽类型：仅做大小限制与基础安全校验
    console.log(`[Upload API] 文件类型: ${file.type || 'unknown'}`);

    // 验证文件大小 (10MB)
    const maxSize = 10 * 1024 * 1024;
    if (file.size > maxSize) {
      console.log(`[Upload API] 错误: 文件大小超过限制 ${file.size} > ${maxSize}`);
      return NextResponse.json({ error: "File size exceeds 10MB limit" }, { status: 400 });
    }

    // 图片：统一上传到 OSS 并返回直链（保持原始图片 MIME，便于 <img> 内联展示）
    if (file.type.startsWith("image/")) {
      try {
        const buffer = Buffer.from(await file.arrayBuffer());
        const key = buildObjectKey(file.name || `image-${Date.now()}.bin`, 'images');
        const safeName = encodeURIComponent(file.name || 'image');
        const out = await uploadBufferToOss({
          buffer,
          key,
          mime: file.type || 'application/octet-stream',
          headers: {
            // 显式 inline，避免被浏览器当做附件下载
            'Content-Disposition': `inline; filename="${safeName}"; filename*=UTF-8''${safeName}`,
          },
        });
        console.log(`[Upload API] 图片上传到 OSS 成功:`, { key: out.key, url: out.url });
        const fileId = `file_${Date.now()}_${Math.random().toString(36).slice(2,9)}`;
        await recordFile({
          fileId,
          kind: 'IMAGE',
          key,
          etag: out.etag,
          mime: file.type || 'application/octet-stream',
          sizeBytes: file.size,
          status: 'ready',
        });
        // 直接生成签名 URL，供前端发送给模型使用（减少二次签名往返）
        try {
          const { signGetUrl } = await import('@/lib/oss');
          const signed = await signGetUrl({ key, expiresSec: 3600 });
          return NextResponse.json({
            fileId,
            url: out.url,
            signedUrl: signed.url,
            expiresAt: signed.expiresAt,
            name: file.name,
            contentType: file.type,
            size: file.size,
            status: "ready",
          });
        } catch (e) {
          // 回退：即使签名失败也返回基本信息
          return NextResponse.json({
            fileId,
            url: out.url,
            name: file.name,
            contentType: file.type,
            size: file.size,
            status: "ready",
          });
        }
      } catch (err: any) {
        console.error(`[Upload API] 图片上传到 OSS 失败:`, err);
        return NextResponse.json({ error: "Image upload failed", details: err?.message }, { status: 500 });
      }
    }

    // 音频：上传到阿里云 OSS 并返回直链 URL
    if (file.type.startsWith("audio/")) {
      try {
        const buffer = Buffer.from(await file.arrayBuffer());
        const key = buildAudioObjectKey(file.name || `recording-${Date.now()}.webm`);
        const out = await uploadBufferToOss({ buffer, key, mime: file.type });
        console.log(`[Upload API] 音频上传到 OSS 成功:`, { key: out.key, url: out.url });
        const fileId = `file_${Date.now()}_${Math.random().toString(36).slice(2,9)}`;
        await recordFile({
          fileId,
          kind: 'AUDIO',
          key,
          etag: out.etag,
          mime: file.type,
          sizeBytes: file.size,
          status: 'ready',
        });
        return NextResponse.json({
          fileId,
          url: out.url,
          name: file.name,
          contentType: file.type,
          size: file.size,
          status: "ready",
        });
      } catch (err: any) {
        console.error(`[Upload API] 音频上传到 OSS 失败:`, err);
        return NextResponse.json({ error: "Audio upload failed", details: err?.message }, { status: 500 });
      }
    }

    // PDF：上传到 OSS（直链），并异步通知后端解析
    if (file.type === "application/pdf") {
      try {
        const buffer = Buffer.from(await file.arrayBuffer());
        const key = buildObjectKey(file.name || `document-${Date.now()}.pdf`, 'pdf');
        const out = await uploadBufferToOss({ buffer, key, mime: file.type });
        console.log(`[Upload API] PDF 上传到 OSS 成功:`, { key: out.key, url: out.url });

        // 异步通知后端解析（不阻塞响应）
        (async () => {
          try {
            const backendBaseUrl = process.env["NEXT_PUBLIC_BACKEND_BASE_URL"] || "http://localhost:8080";
            const category = (formData.get("category") as string) || null;
            const params = new URLSearchParams();
            if (category) params.set('category', category);
            params.set('source', 'oss');
            params.set('url', out.url);
            const notifyUrl = `${backendBaseUrl}/api/documents/uploadByUrl?${params.toString()}`;
            const headers = await withAuthHeaders();
            await fetch(notifyUrl, { method: 'POST', headers });
            console.log(`[Upload API] 已通知后端解析: ${notifyUrl}`);
          } catch (e) {
            console.warn(`[Upload API] 通知后端解析失败:`, e);
          }
        })();

        return NextResponse.json({
          fileId: await (async () => {
            const fileId = `file_${Date.now()}_${Math.random().toString(36).slice(2,9)}`;
            await recordFile({
              fileId,
              kind: 'DOCUMENT',
              key,
              etag: out.etag,
              mime: file.type,
              sizeBytes: file.size,
              status: 'ready',
            });
            return fileId;
          })(),
          url: out.url,
          name: file.name,
          contentType: file.type,
          size: file.size,
          status: "ready",
        });
      } catch (err: any) {
        console.error(`[Upload API] PDF 上传到 OSS 失败:`, err);
        return NextResponse.json({ error: "PDF upload failed", details: err?.message }, { status: 500 });
      }
    }

    // 生成唯一文件ID
    const fileId = `file_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
    
    // 其他文件：统一上传到 OSS 并返回直链
    const buffer = Buffer.from(await file.arrayBuffer());
    const key = buildObjectKey(file.name || `file-${Date.now()}.bin`, 'files');
    const out = await uploadBufferToOss({ buffer, key, mime: file.type || 'application/octet-stream' });

    console.log(`[Upload API] 文件上传到 OSS 成功:`, { fileId, key: out.key, url: out.url, name: file.name });
    await recordFile({
      fileId,
      kind: 'OTHER',
      key,
      etag: out.etag,
      mime: file.type || 'application/octet-stream',
      sizeBytes: file.size,
      status: 'ready',
    });

    // 返回文件信息（非PDF：直接标记为 ready，避免前端轮询后端状态）
    return NextResponse.json({
      fileId,
      url: out.url,
      name: file.name,
      contentType: file.type,
      size: file.size,
      status: "ready",
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
