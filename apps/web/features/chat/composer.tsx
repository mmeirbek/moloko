"use client";

import { ComposerPrimitive, ThreadPrimitive, useAui, useAuiState } from "@assistant-ui/react";
import { useTranslations } from "next-intl";
import type { ClipboardEvent, ReactNode } from "react";

import { ArrowUp, Network, Square } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { AgentAvatar, AvatarArt } from "@/features/agents/agent-avatar";
import { BOSS_LOOK } from "@/features/agents/agent-looks";
import { MicButton } from "@/features/voice/mic-button";
import { cn } from "@/lib/utils";

import { mentionSuggestions, parseAgentMention } from "./agent-mention";
import { useMentionAgents } from "./use-agent-task";

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

/** The agent's face; the Orchestrator's aliases show its crowned cow. */
function MentionFace({ agent, size }: { agent: { id: string; orchestrator?: boolean }; size: number }) {
  return agent.orchestrator ? <AvatarArt look={BOSS_LOOK} size={size} /> : <AgentAvatar agentId={agent.id} size={size} />;
}

/** While «@…» is typed: the agents to pick; once one is named, whose task it becomes. */
function AgentMentions() {
  const t = useTranslations("chat");
  const aui = useAui();
  const text = useAuiState((s) => s.composer.text);
  const agents = useMentionAgents();
  const named = parseAgentMention(text, agents);
  const options = mentionSuggestions(text, agents);
  if (named) {
    return (
      <p className="flex items-center gap-1.5 px-4 pt-3 text-xs text-sky" role="status" data-testid="mention-target">
        <MentionFace agent={named.agent} size={18} /> {t("mention.target", { name: named.agent.name })}
      </p>
    );
  }
  if (options.length === 0) return null;
  return (
    <ul className="flex flex-wrap gap-1 px-3 pt-3" aria-label={t("mention.pick")}>
      {options.map((agent) => (
        <li key={agent.id}>
          <button
            type="button"
            onClick={() => aui.composer().setText(`@${agent.name} `)}
            className="inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs hover:bg-accent"
          >
            <MentionFace agent={agent} size={18} /> {agent.name}
          </button>
        </li>
      ))}
    </ul>
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
        "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50",
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
  onPaste,
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
  /** A paste with files in it (screenshots, copied files) attaches them. */
  onPaste?: (e: ClipboardEvent) => void;
  className?: string;
}) {
  const t = useTranslations("chat");
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <ComposerPrimitive.Root
        onPaste={onPaste}
        className={cn(
          "flex flex-col bg-card transition-colors focus-within:ring-2 focus-within:ring-ring/40 pixel-frame",
          agents && "border-sky/60",
        )}
      >
        {chips}
        <AgentMentions />
        <ComposerPrimitive.Input
          rows={1}
          autoFocus
          disabled={disabled}
          placeholder={agents ? t("placeholderAgents") : t("placeholder")}
          className="max-h-60 min-h-14 w-full resize-none bg-transparent px-4 pt-4 pb-1 text-base outline-none placeholder:text-muted-foreground"
        />
        <div className="flex items-center gap-1 px-2 pb-2">
          {attach}
          <AgentsSwitch on={agents} onChange={onAgentsChange} disabled={disabled} />
          <div className="min-w-0 flex-1" />
          {model}
          <ComposerMic disabled={disabled} />
          <ThreadPrimitive.If running={false}>
            <ComposerPrimitive.Send asChild>
              <Button size="icon" aria-label={t("send")} className="shrink-0">
                <ArrowUp />
              </Button>
            </ComposerPrimitive.Send>
          </ThreadPrimitive.If>
          <ThreadPrimitive.If running>
            <ComposerPrimitive.Cancel asChild>
              <Button size="icon" variant="outline" aria-label={t("stop")} className="shrink-0">
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
