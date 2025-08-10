import { NextRequest, NextResponse } from "next/server";

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ fileId: string }> }
) {
  try {
    const { fileId } = await params;
    const body = await request.json();
    const { threadId } = body;

    if (!fileId) {
      return NextResponse.json({ error: "No fileId provided" }, { status: 400 });
    }

    // threadId 现在是可选的，不再强制要求
    console.log(`Deleting file: ${fileId}${threadId ? ` from thread: ${threadId}` : ''}`);

    // 模拟文件删除操作
    // 在实际应用中，这里应该从云存储服务删除文件

    // 返回成功响应
    return NextResponse.json({
      success: true,
      message: `File ${fileId} deleted successfully`,
    });

  } catch (error: any) {
    console.error("Delete error:", error);
    return NextResponse.json(
      { error: "Delete failed", details: error.message },
      { status: 500 }
    );
  }
}

export async function OPTIONS() {
  return new NextResponse(null, {
    status: 204,
    headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "DELETE, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    },
  });
} 