# Third-party notices

moloko depends on open-source packages listed (with versions and licenses) in the
dependency register in `docs/decisions.md`. Those are used as packages and keep
their own license files inside `node_modules/` / the Python environment.

This file lists **source code adapted into this repository**. Code from REFERENCE
repositories (see `docs/external-repositories.md`) must never be copied without
being listed here with its license notice.

## shadcn/ui

Component patterns in `apps/web/components/ui/` (`button.tsx`, `input.tsx`,
`card.tsx`) are adapted from shadcn/ui — https://github.com/shadcn-ui/ui

```
MIT License

Copyright (c) 2023 shadcn

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## phaserjs/template-nextjs

The React ⇄ Phaser bridge architecture in `apps/web/features/office/` (a client-only
component that dynamically imports the game and an event bus between React and the
scene, see `engine/bus.ts`, `engine/createGame.ts`, `office-view.tsx`) follows
https://github.com/phaserjs/template-nextjs

```
MIT License

Copyright (c) 2025 Phaser

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Assets

No third-party art assets. All Pixel Office art is original and drawn in code; every
asset is listed with its source and license in `apps/web/assets/MANIFEST.md`
(spec 18.2). The brand logo belongs to the owner.
