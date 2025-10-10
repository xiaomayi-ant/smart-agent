import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  _req: NextRequest,
  { params }: { params: { filename: string } }
) {
  try {
    const fs = await import("fs/promises");
    const path = await import("path");

    const filename = params.filename;
    const baseDir = path.join(process.cwd(), ".uploads", "audio");
    const filePath = path.join(baseDir, filename);

    const data = await fs.readFile(filePath);

    const ext = path.extname(filename).toLowerCase();
    const type =
      ext === ".webm"
        ? "audio/webm"
        : ext === ".wav"
        ? "audio/wav"
        : ext === ".mp3"
        ? "audio/mpeg"
        : "application/octet-stream";

    return new NextResponse(data, {
      status: 200,
      headers: {
        "Content-Type": type,
        "Cache-Control": "public, max-age=31536000, immutable",
      },
    });
  } catch (e: any) {
    return NextResponse.json({ error: e?.message || "Not found" }, { status: 404 });
  }
}


