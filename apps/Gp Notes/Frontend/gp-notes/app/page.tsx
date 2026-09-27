import Workspace from "./components/Workspace";
import { configuration, liveReady } from "@/lib/service";
export const dynamic = "force-dynamic";
export default function Page() {
  return <Workspace liveAvailable={liveReady(configuration())} />;
}
