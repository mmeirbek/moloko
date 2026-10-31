import { TaskDetailView } from "@/features/tasks/task-detail";

export default async function TaskPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <TaskDetailView key={id} taskId={id} />;
}
