import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { PageHeader } from "@/components/layout/page-header";
import { TasksView } from "@/features/tasks/tasks-view";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("pages.tasks");
  return { title: t("title") };
}

export default async function TasksPage() {
  const t = await getTranslations("pages.tasks");
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <TasksView />
    </>
  );
}
