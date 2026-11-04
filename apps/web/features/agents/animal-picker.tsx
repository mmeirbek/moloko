"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { AvatarArt } from "./agent-avatar";
import { ANIMALS, BACKDROPS, type Look, type Species } from "./agent-looks";

const face = (animal: Species, i: number): Look => ({ animal, accessory: "none", expression: "happy", backdrop: BACKDROPS[i % BACKDROPS.length]! });

/** A die for «Случайное»: the server picks a species the office has fewest of. */
function Die({ size }: { size: number }) {
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} aria-hidden="true" className="shrink-0 rounded-full">
      <circle cx="32" cy="32" r="32" fill="var(--muted)" />
      <rect x="17" y="17" width="30" height="30" rx="7" fill="var(--card)" stroke="currentColor" strokeWidth="2" />
      {[
        [25, 25],
        [39, 25],
        [32, 32],
        [25, 39],
        [39, 39],
      ].map(([cx, cy]) => (
        <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r="2.6" fill="currentColor" />
      ))}
    </svg>
  );
}

/**
 * Which animal the agent is (owner: «список животных, которых я могу выбрать при создании»):
 * the current choice, and the whole list on request — every exotic species by its face and
 * name, or «Случайное».
 */
export function AnimalPicker({ value, onChange, id }: { value: Species | ""; onChange: (animal: Species | "") => void; id: string }) {
  const t = useTranslations("animals");
  const [open, setOpen] = useState(false);
  const name = (animal: Species | "") => (animal ? t(animal) : t("random"));
  const current = value ? <AvatarArt look={face(value, ANIMALS.indexOf(value))} size={40} /> : <Die size={40} />;
  return (
    <div className="flex flex-col gap-2" data-testid="animal-picker">
      <div className="flex items-center gap-3">
        {current}
        <span id={id} className="min-w-0 flex-1 text-sm font-medium">
          {name(value)}
        </span>
        <Button type="button" size="sm" variant="outline" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          {open ? t("done") : t("choose")}
        </Button>
      </div>
      {open && (
        <div role="radiogroup" aria-labelledby={id} className="grid grid-cols-3 gap-1.5 sm:grid-cols-4 md:grid-cols-5">
          {(["", ...ANIMALS] as const).map((animal, i) => {
            const checked = value === animal;
            return (
              <button
                key={animal || "random"}
                type="button"
                role="radio"
                aria-checked={checked}
                onClick={() => {
                  onChange(animal);
                  setOpen(false);
                }}
                className={cn(
                  "flex flex-col items-center gap-1 rounded-lg border px-1 py-2 text-center text-xs leading-tight outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring",
                  checked ? "border-primary bg-accent" : "border-transparent",
                )}
                data-animal={animal || "random"}
              >
                {animal ? <AvatarArt look={face(animal, i)} size={44} /> : <Die size={44} />}
                <span className="line-clamp-2">{name(animal)}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
