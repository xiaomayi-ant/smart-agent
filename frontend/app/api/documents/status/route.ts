import { NextRequest, NextResponse } from "next/server";

export async function GET(request: NextRequest) {
  try {
    const fileId = request.nextUrl.searchParams.get("fileId");
    
    console.log(`[Status API] 查询文件状态: ${fileId}`);

    if (!fileId) {
      console.log(`[Status API] 错误: 没有提供 fileId`);
      return NextResponse.json({ error: "No fileId provided" }, { status: 400 });
    }

    // 代理到后端状态查询接口
    const backendBaseUrl = process.env["NEXT_PUBLIC_BACKEND_BASE_URL"] || "http://localhost:8080";
    const targetUrl = `${backendBaseUrl}/api/documents/status?fileId=${encodeURIComponent(fileId)}`;

    console.log(`[Status API] 代理转发到后端: ${targetUrl}`);

    const backendRes = await fetch(targetUrl, {
      method: "GET",
    });

    // 直接透传后端状态码与结果
    const text = await backendRes.text();
    try {
      const json = JSON.parse(text);
      return NextResponse.json(json, { status: backendRes.status });
    } catch {
      // 后端返回非JSON时，包装为对象
      return NextResponse.json({ raw: text }, { status: backendRes.status });
    }

  } catch (error: any) {
    console.error("[Status API] 查询错误:", error);
    return NextResponse.json(
      { error: "Status query failed", details: error.message },
      { status: 500 }
    );
  }
}

export async function OPTIONS() {
  return new NextResponse(null, {
    status: 204,
    headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    },
  });
}
