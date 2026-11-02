import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { IslandShell } from "@/features/island/island-shell";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("island");
  return { title: t("title") };
}

/** The island alone (Mac notch app, apps/mac-island). Signed-out visitors go to /login?next=/island. */
export default function IslandPage() {
  return <IslandShell />;
}
