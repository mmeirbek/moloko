/**
 * The office characters are the agents' animals (owner: «агенты должны быть животными
 * соответственно своим иконкам») — the same species as their faces (features/agents), as
 * original 16×16 pixel art drawn in code (assets/MANIFEST.md). A species is a head of 7 rows
 * put on the shared body frames (sprites.ts FRAMES): it replaces the human head, the arms take
 * the fur colour. Pure: tested.
 *
 * Head keys: . transparent  a fur  b light fur / face  k dark marks  n nose / accent
 * x second accent  e eyes  w white.
 */
import type { Species } from "@/features/agents/agent-looks";

export interface AnimalArt {
  head: string[];
  colors: { a: string; b: string; k: string; n: string; x?: string; w?: string };
  /** eye colour (dark by default; light on dark faces) */
  eyes?: string;
}

export const ANIMAL_ART: Record<Species, AnimalArt> = {
  amur_tiger: {
    head: ["....aa....aa....", "...aaaakkaaaa...", "...kaaaaaaaaak..", "...aaeaaaaeaa...", "...kabbbbbbak...", "....bbbnnbbb....", ".....bbbbbb....."],
    colors: { a: "#e8742c", b: "#fff3e3", k: "#2b2b2b", n: "#d1606a" },
  },
  snow_leopard: {
    head: ["....aa....aa....", "...aakaaaakaa...", "...aaaakaaaaa...", "...aaeaaaaeaa...", "...kabbbbbbak...", "....bbbnnbbb....", ".....bbbbbb....."],
    colors: { a: "#d9d6cf", b: "#f8f7f3", k: "#5a5a5a", n: "#e39aa0" },
  },
  pallas_cat: {
    head: ["................", "...aaaaaaaaaa...", "..aaakakkakaaa..", ".aaxexaaaaxexaa.", ".aakaabbbbaakaa.", "..aaabbnnbbaaa..", "....aabbbbaa...."],
    colors: { a: "#a99e92", b: "#f1ece4", k: "#3d3530", n: "#c77a7a", x: "#efe2b0" },
  },
  fennec_fox: {
    head: ["..aa........aa..", "..ana......ana..", "..anaaaaaaaana..", "...aaeaaaaeaa...", "...abbbbbbbba...", "....bbbkkbbb....", ".....bbbbbb....."],
    colors: { a: "#f0d3a4", b: "#fff6e8", k: "#2b2b2b", n: "#f2b8a8" },
  },
  red_panda: {
    head: ["...bb......bb...", "...baaaaaaaab...", "...abbaaaabba...", "...aaeaaaaeaa...", "...bakbbbbkab...", "....bkbnnbkb....", ".....bbbbbb....."],
    colors: { a: "#c4521f", b: "#fbf6ee", k: "#7a2d12", n: "#2b2b2b" },
  },
  capybara: {
    head: ["...aa......aa...", "...aaaaaaaaaa...", "...aaeaaaaeaa...", "...aaaaaaaaaa...", "...abbbbbbbba...", "...abkbbbbkba...", "....bbbbbbbb...."],
    colors: { a: "#a47b55", b: "#8e6748", k: "#3b2a1d", n: "#3b2a1d" },
  },
  axolotl: {
    head: ["................", ".n..aaaaaaaa..n.", "..nnaaaaaaaann..", ".n.aeaaaaaaea.n.", "..nnabaaaabann..", "....aakkkkaa....", ".....aaaaaa....."],
    colors: { a: "#f6b5c8", b: "#ef8fa8", k: "#2b2b2b", n: "#e0607e" },
  },
  quokka: {
    head: ["...aa......aa...", "...abaaaaaaba...", "...aaaaaaaaaa...", "...aaeaaaaeaa...", "...aabbkkbbaa...", "....bkbbbbkb....", ".....bbkkbb....."],
    colors: { a: "#a9825c", b: "#c9a27f", k: "#2b2b2b", n: "#2b2b2b" },
  },
  okapi: {
    head: ["..nn..n..n..nn..", ".nnnaaaaaaaannn.", "....aaaaaaaa....", "....aeaaaaea....", "....baaaaaab....", "....bbbkkbbb....", ".....bbbbbb....."],
    colors: { a: "#5a3628", b: "#f1e6d6", k: "#2b2b2b", n: "#4a2c22" },
    eyes: "#f1e6d6",
  },
  tarsier: {
    head: [".bb..........bb.", ".bab.aaaaaa.bab.", "..aaaaaaaaaaaa..", "..axexaaaaxexa..", "..axxxaaaaxxxa..", "...aaaakkaaaa...", ".....aaaaaa....."],
    colors: { a: "#c49a74", b: "#e2b9a0", k: "#6b4a2e", n: "#6b4a2e", x: "#e8a43c" },
  },
  ring_tailed_lemur: {
    head: ["...a........a...", "...aa.aaaa.aa...", "...abbbbbbbba...", "...bkebbbbekb...", "...bkkbbbbkkb...", "....bbbkkbbb....", ".....bbkkbb....."],
    colors: { a: "#9a9a9c", b: "#f5f5f3", k: "#2b2b2b", n: "#2b2b2b" },
    eyes: "#f2b234",
  },
  malayan_tapir: {
    head: ["...bb......bb...", "...baaaaaaaab...", "...aaaaaaaaaa...", "...aaeaaaaeaa...", "....aaaaaaaa....", "......nnnn......", "......nkkn......"],
    colors: { a: "#2f3033", b: "#f4f4f4", k: "#1f1f22", n: "#4a4b50" },
    eyes: "#f4f4f4",
  },
  sea_otter: {
    head: ["................", "...aaaaaaaaaa...", "..aabbbbbbbbaa..", "..abbebbbbebba..", "..abbbnkknbbba..", "...abnnnnnnba...", "....aabbbbaa...."],
    colors: { a: "#7b563b", b: "#e8dccb", k: "#2b2b2b", n: "#f5efe6" },
  },
  atlantic_puffin: {
    head: ["................", "....aaaaaaaa....", "...aaaaaaaaaa...", "...abebbbbeba...", "...abbbkkbbba...", "....abbnnbba....", "......xxxx......"],
    colors: { a: "#222326", b: "#f2f2f0", k: "#5d6b78", n: "#f2c14e", x: "#e8552e" },
  },
  three_toed_sloth: {
    head: ["................", "....aaaaaaaa....", "...abbbbbbbba...", "...kkebbbbekk...", "...abbbnnbbba...", "....bkbbbbkb....", ".....bbkkbb....."],
    colors: { a: "#9b8468", b: "#e9dcc4", k: "#4a3626", n: "#3a2a1e" },
    eyes: "#e9dcc4",
  },
  platypus: {
    head: ["................", "....aaaaaaaa....", "...aaaaaaaaaa...", "...aaeaaaaeaa...", "..xxxxxxxxxxxx..", "..xnnknnnnknnx..", "...xxxxxxxxxx..."],
    colors: { a: "#7a5537", b: "#7a5537", k: "#23272e", n: "#4f5866", x: "#3f4651" },
  },
  barn_owl: {
    head: ["................", "...aaaaaaaaaa...", "...abbbaabbba...", "...bbebbbbebb...", "...abbbnnbbba...", "....abbnnbba....", ".....abbbba....."],
    colors: { a: "#d9a35a", b: "#fbf6ee", k: "#c58e48", n: "#e6c9a8" },
  },
  saiga: {
    head: ["....x......x....", "....x.aaaa.x....", "..aa.xaaaax.aa..", "....aeaaaaea....", "....aaaaaaaa....", "...nnnnnnnnnn...", "...nnknnnnknn..."],
    colors: { a: "#d4b07a", b: "#d4b07a", k: "#5c4528", n: "#c79f69", x: "#e8d6a8" },
  },
  mandrill: {
    head: ["................", "...aaaaaaaaaa...", "...akkkkkkkka...", "...aaeaaaaeaa...", "...axxxnnxxxa...", "...axxxnnxxxa...", "....bbbnnbbb...."],
    colors: { a: "#6f6a3d", b: "#f1e6b8", k: "#3e3a20", n: "#d93b3b", x: "#4a7fd1" },
  },
  emperor_tamarin: {
    head: ["................", "....aaaaaaaa....", "...aakkkkkkaa...", "...akekkkkeka...", "...akkkkkkkka...", "..wwwkkkkkkwww..", ".ww...kkkk...ww."],
    colors: { a: "#5f5a57", b: "#5f5a57", k: "#2f2c2b", n: "#2f2c2b", w: "#f7f7f5" },
    eyes: "#f2f2ee",
  },
};

const HEAD_ROWS = 7;
const HUMAN_HEAD = new Set(["h", "s", "e", "o"]);

/** The row where a frame's head starts (poses bob or slump the head down a row or two). */
function headTop(grid: string[]): number {
  const hair = grid.findIndex((row) => row.includes("h"));
  return hair < 0 ? 0 : hair - 1;
}

/**
 * One body frame with the species' head: front-facing frames show the face, the typing frames
 * (seen from behind) only fur; "think2" glances aside, "read2" looks down at the papers.
 */
export function animalFrame(name: string, base: string[], species: Species): string[] {
  const art = ANIMAL_ART[species];
  const back = name.startsWith("type");
  const top = headTop(base);
  const out = base.map((row) => row.split(""));
  for (let r = 0; r < HEAD_ROWS; r++) {
    const y = top + r;
    if (y < 0 || y >= out.length) continue;
    const row = out[y]!;
    for (let x = 3; x <= 12; x++) if (HUMAN_HEAD.has(row[x]!)) row[x] = ".";
    const line = art.head[r]!;
    for (let x = 0; x < line.length; x++) {
      let ch = line[x]!;
      if (ch === ".") continue;
      if (back && ch !== "a" && ch !== "k") ch = "a"; // seen from behind: fur and its marks only
      else if (ch === "e" && name === "read2") ch = "b"; // looking down at the papers
      else if (ch === "e" && name === "think2") {
        // glancing aside: the eye moves one pixel right, fur fills where it was
        ch = x > 0 && line[x - 1] !== "." ? line[x - 1]! : "a";
        row[x] = ch;
        if (x + 1 < row.length) row[x + 1] = "e";
        x++;
        continue;
      }
      row[x] = ch;
    }
  }
  return out.map((row) => row.join(""));
}
