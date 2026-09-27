import { handle } from "@/lib/provider";
export const runtime = "nodejs";
export const maxDuration = 120;
export async function POST(request: Request) {
  return handle(request, "audio");
}
