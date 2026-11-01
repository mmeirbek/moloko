import { getTranslations } from "next-intl/server";

import { PageHeader } from "./page-header";

type Section = "chat" | "subagentOffice" | "agentOffice" | "tasks" | "integrations";

/** Placeholder for sections built in later sprints (spec section 24). */
export async function ComingSoon({ section, sprint }: { section: Section; sprint: number }) {
  const t = await getTranslations("pages");
  return (
    <>
      <PageHeader title={t(`${section}.title`)} description={t(`${section}.description`)} />
      <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
        {t("comingSoon", { sprint })}
      </div>
    </>
  );
}
