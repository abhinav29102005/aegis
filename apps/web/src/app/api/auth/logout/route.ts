import { cookies } from "next/headers";
import { NextResponse } from "next/server";

export async function POST() {
  const cookieStore = await cookies();
  cookieStore.delete("aegis_session");
  cookieStore.delete("aegis_tenant_id");
  return NextResponse.json({ ok: true, status: "logged_out" });
}

export async function GET() {
  const cookieStore = await cookies();
  cookieStore.delete("aegis_session");
  cookieStore.delete("aegis_tenant_id");
  return NextResponse.json({ ok: true, status: "logged_out" });
}
