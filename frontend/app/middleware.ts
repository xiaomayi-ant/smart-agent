import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

export const config = {
  matcher: ["/((?!_next/|static/|public/).*)"],
};

export async function middleware(req: NextRequest) {
  try {
    const sid = req.cookies.get("sid")?.value;
    if (!sid) {
      const url = new URL("/api/auth/guest", req.nextUrl.origin);
      // 以内部重写方式确保首包前下发 Cookie
      const res = NextResponse.rewrite(url);
      return res;
    }
  } catch {}
  return NextResponse.next();
}


