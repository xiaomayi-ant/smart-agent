import { NextRequest, NextResponse } from 'next/server';
import { signGetUrl } from '@/lib/oss';

/**
 * POST /api/files/sign
 * 生成 OSS 签名 URL（用于私有桶图片临时访问）
 */
export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const { key, expiresSec } = body;

    if (!key || typeof key !== 'string') {
      return NextResponse.json(
        { error: 'Missing or invalid key parameter' },
        { status: 400 }
      );
    }

    // 生成签名 URL
    const result = await signGetUrl({
      key,
      expiresSec: expiresSec || 3600, // 默认 1 小时
    });

    return NextResponse.json(result);
  } catch (error: any) {
    console.error('[API /api/files/sign] Error:', error);
    return NextResponse.json(
      { error: error.message || 'Failed to generate signed URL' },
      { status: 500 }
    );
  }
}

