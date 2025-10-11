import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

export const config = {
  matcher: ["/((?!_next/|static/|public/|api/auth/guest).*)"],
};

export async function middleware(req: NextRequest) {
  try {
    const sid = req.cookies.get("sid")?.value;
    if (!sid && !req.nextUrl.pathname.startsWith('/api/auth/')) {
      // 没有 sid 时，先重定向到 guest 接口获取 cookie
      const guestUrl = new URL("/api/auth/guest", req.nextUrl.origin);
      guestUrl.searchParams.set("redirect", req.nextUrl.pathname + req.nextUrl.search);
      return NextResponse.redirect(guestUrl);
    }
  } catch {}
  return NextResponse.next();
}


