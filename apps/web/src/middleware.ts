import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const PROTECTED_PREFIXES = [
  "/dashboard",
  "/agents",
  "/passports",
  "/payments",
  "/ghostpay",
  "/disputes",
  "/audit",
  "/developer",
  "/settings",
  "/onboarding",
];

const AUTH_PAGES = ["/login"];

const CSP_POLICY =
  "default-src 'self'; script-src 'self' 'unsafe-eval' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self' http://localhost:* http://127.0.0.1:* https://*; frame-ancestors 'none'; base-uri 'self'; form-action 'self';";

function applySecurityHeaders(response: NextResponse): NextResponse {
  response.headers.set("Content-Security-Policy", CSP_POLICY);
  response.headers.set("Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload");
  response.headers.set("X-Frame-Options", "DENY");
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  response.headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  return response;
}

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const sessionToken = request.cookies.get("aegis_session")?.value;

  const isProtected = PROTECTED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
  const isAuthPage = AUTH_PAGES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );

  // If trying to access protected route without cookie, redirect cleanly to login
  if (isProtected && !sessionToken) {
    const loginUrl = new URL("/login", request.url);
    if (pathname !== "/dashboard") {
      loginUrl.searchParams.set("next", `${pathname}${search}`);
    }
    const redirectResponse = NextResponse.redirect(loginUrl);
    return applySecurityHeaders(redirectResponse);
  }

  // If already authenticated and visiting /login, redirect to /dashboard
  if (isAuthPage && sessionToken) {
    const redirectResponse = NextResponse.redirect(new URL("/dashboard", request.url));
    return applySecurityHeaders(redirectResponse);
  }

  const response = NextResponse.next();
  return applySecurityHeaders(response);
}

export const config = {
  matcher: [
    /*
     * Match all request paths except for:
     * - api (API routes)
     * - _next/static (static files)
     * - _next/image (image optimization files)
     * - favicon.ico, sitemap.xml, robots.txt (metadata files)
     */
    "/((?!api|_next/static|_next/image|favicon.ico|sitemap.xml|robots.txt).*)",
  ],
};
