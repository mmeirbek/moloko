import { EventEmitter } from "node:events";

// Внутренняя шина: всё, что происходит в офисе, летит сюда, а отсюда — в браузеры по SSE.
export type OfficeEvent =
  | { type: "agent"; agent: unknown }
  | { type: "agent_deleted"; id: string }
  | { type: "task"; task: unknown }
  | { type: "message"; message: unknown }
  | { type: "question"; question: unknown }
  | { type: "file"; path: string; deleted?: boolean };

export const bus = new EventEmitter();
bus.setMaxListeners(100);

export function emit(event: OfficeEvent) {
  bus.emit("office", event);
}
