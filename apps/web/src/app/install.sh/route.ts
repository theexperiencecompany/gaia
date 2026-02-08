import { readFile } from "fs/promises";
import { NextResponse } from "next/server";
import { join } from "path";

export async function GET() {
  try {
    const scriptPath = join(process.cwd(), "public", "install.sh");
    const script = await readFile(scriptPath, "utf-8");

    return new NextResponse(script, {
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "public, max-age=3600",
      },
    });
  } catch (error) {
    return new NextResponse("Install script not found", { status: 404 });
  }
}
