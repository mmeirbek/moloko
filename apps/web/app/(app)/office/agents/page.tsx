import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { ComingSoon } from "@/components/layout/coming-soon";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("pages.agentOffice");
  return { title: t("title") };
}

export default function Page() {
  return <ComingSoon section="agentOffice" sprint={6} />;
}
