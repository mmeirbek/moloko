"use client";

import { ComposerPrimitive, ThreadPrimitive, useAui } from "@assistant-ui/react";
import { ArrowUp, Network, Square } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { MicButton } from "@/features/voice/mic-button";
import { cn } from "@/lib/utils";

/** Voice input appends the spoken text to what is already typed. */
function ComposerMic({ disabled }: { disabled?: boolean }) {
  const aui = useAui();
  return (
    <MicButton
      disabled={disabled}
      onText={(text) => {
        const composer = aui.composer();
        const current = composer.getState().text;
        composer.setText(current ? `${current.trimEnd()} ${text}` : text);
      }}
    />
  );
}

/** "Hand to agents": the message goes to the Orchestrator instead of one model. */
function AgentsSwitch({ on, onChange, disabled }: { on: boolean; onChange: (on: boolean) => void; disabled?: boolean }) {
  const t = useTranslations("chat");
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={t("agentsMode")}
      title={t("agentsModeHint")}
      disabled={disabled}
      onClick={() => onChange(!on)}
      className={cn(
        "inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50",
        on
          ? "border-sky/60 bg-sky/15 text-sky"
          : "border-transparent text-muted-foreground hover:bg-accent hover:text-foreground",
      )}
    >
      <Network className="size-4" aria-hidden />
      <span className="hidden sm:inline">{t("agentsMode")}</span>
    </button>
  );
}

/**
 * The message box, the same in a new and an open chat: text on top, then one toolbar —
 * files and the agents switch on the left; model, voice and send on the right.
 */
export function Composer({
  disabled,
  agents,
  onAgentsChange,
  attach,
  chips,
  model,
  className,
}: {
  disabled?: boolean;
  agents: boolean;
  onAgentsChange: (on: boolean) => void;
  /** The attach button (none in agents mode). */
  attach?: ReactNode;
  /** Files waiting to be sent with the message. */
  chips?: ReactNode;
  /** The model picker. */
  model?: ReactNode;
  className?: string;
}) {
  const t = useTranslations("chat");
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <ComposerPrimitive.Root
        className={cn(
          "flex flex-col rounded-3xl border bg-card shadow-sm transition-colors focus-within:ring-2 focus-within:ring-ring/40",
          agents && "border-sky/60",
        )}
      >
        {chips}
        <ComposerPrimitive.Input
          rows={1}
          autoFocus
          disabled={disabled}
          placeholder={agents ? t("placeholderAgents") : t("placeholder")}
          className="max-h-60 min-h-14 w-full resize-none bg-transparent px-4 pt-4 pb-1 text-base outline-none placeholder:text-muted-foreground md:text-[15px]"
        />
        <div className="flex items-center gap-1 px-2 pb-2">
          {attach}
          <AgentsSwitch on={agents} onChange={onAgentsChange} disabled={disabled} />
          <div className="min-w-0 flex-1" />
          {model}
          <ComposerMic disabled={disabled} />
          <ThreadPrimitive.If running={false}>
            <ComposerPrimitive.Send asChild>
              <Button size="icon" aria-label={t("send")} className="shrink-0 rounded-full">
                <ArrowUp />
              </Button>
            </ComposerPrimitive.Send>
          </ThreadPrimitive.If>
          <ThreadPrimitive.If running>
            <ComposerPrimitive.Cancel asChild>
              <Button size="icon" variant="outline" aria-label={t("stop")} className="shrink-0 rounded-full">
                <Square />
              </Button>
            </ComposerPrimitive.Cancel>
          </ThreadPrimitive.If>
        </div>
      </ComposerPrimitive.Root>
      {agents && <p className="px-4 text-xs text-muted-foreground">{t("agentsModeHint")}</p>}
    </div>
  );
}

/** Example questions: a tap puts one into the composer to edit or send. */
export function Suggestions({ className }: { className?: string }) {
  const t = useTranslations("chat");
  const aui = useAui();
  const items = [t("suggestions.explain"), t("suggestions.plan"), t("suggestions.letter")];
  return (
    <ul className={cn("grid grid-cols-1 gap-2 sm:grid-cols-3", className)} aria-label={t("suggestions.label")}>
      {items.map((text) => (
        <li key={text} className="flex">
          <button
            type="button"
            onClick={() => aui.composer().setText(text)}
            className="w-full rounded-2xl border bg-card px-3.5 py-3 text-left text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            {text}
          </button>
        </li>
      ))}
    </ul>
  );
}
