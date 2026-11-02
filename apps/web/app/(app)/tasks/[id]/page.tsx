import { TaskDetailView } from "@/features/tasks/task-detail";

/** The task as a chat: full width (the details sit in the right bar), like the chat pages. */
export default async function TaskPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <TaskDetailView key={id} taskId={id} />;
}
