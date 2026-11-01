# Asset manifest (spec 18.2)

Every visual asset of the Pixel Office, with its source and license.

| Asset | Where | Source | License |
|---|---|---|---|
| Characters (16×16, 17 frames: stand, breathe, walk ×2, type ×2, think ×2, read ×2, wait ×2, cheer ×2, slump ×2) | `features/office/engine/sprites.ts` (`FRAMES`) | Original pixel art drawn in code for moloko | Owner's (project) |
| Status icons (8×8: thinking, hourglass, document, pause, check, alert, envelope) | `features/office/engine/sprites.ts` (`ICONS`) | Original, drawn in code | Owner's (project) |
| Floor, walls, windows, desks, monitors, task board, bookshelves, sofa, rug, meeting table, bench, plants | `features/office/engine/OfficeScene.ts` (`drawStatic`) | Original, drawn with Phaser Graphics | Owner's (project) |
| Floor plan | `features/office/engine/map.ts` (`LAYOUT`) | Original | Owner's (project) |
| Brand logo (placeholder until the owner's PNG) | `components/brand/logo.tsx` | Original placeholder; the real logo belongs to the owner | Owner's |

No third-party art is used. Before adding any external asset pack: confirm its license,
ask the owner (docs/external-repositories.md rule 3), keep the style unified, and add a
row here.
