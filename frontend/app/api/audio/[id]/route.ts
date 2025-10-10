import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";

export const runtime = "nodejs";

export async function GET(_req: NextRequest, { params }: { params: { id: string } }) {
  try {
    const id = params.id;
    const audio = await prisma.audioInput.findUnique({ where: { id } });
    if (!audio) return new NextResponse("Not Found", { status: 404 });
    if (audio.storage === "url" && audio.url) {
      // redirect to external storage
      return NextResponse.redirect(audio.url, { status: 302 });
    }
    const mime = audio.mime || "audio/mpeg";
    const body = audio.blob as Buffer | null;
    if (!body) return new NextResponse("No Content", { status: 204 });
    return new NextResponse(body, {
      status: 200,
      headers: {
        "Content-Type": mime,
        "Cache-Control": "public, max-age=31536000, immutable",
      },
    });
  } catch (e) {
    return new NextResponse("Server Error", { status: 500 });
  }
}


