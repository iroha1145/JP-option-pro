# Third-Party Notices

## Feel and icon motion adaptations

The Japanese interface ports the motion implementation from the US site's
reviewed source commit `a6339af032163a1ad4554d523831cbf0b670308c`.

- Feel: https://github.com/diip3sh/feel
  - Reference commit: `c9b22fa42b25757852d7c3aa621344d13882a519`
  - Adapted fixed spring parameters, rubber-band walls, momentum projection,
    internal RK4 spring simulation and animation handoff
    in `frontend-src/src/lib/feel.ts`.
- Lucide Animated: https://github.com/pqoqubbw/icons
  - Reference commit: `4662fff2b60fdcf4751b32013606756caf7c4c26`
  - Reference for per-part SVG micro-choreographies in
    `frontend-src/src/components/icons.tsx` and
    `frontend-src/src/styles/icon-motion.css`.

These references are not contacted at runtime. Existing project paths and
Japanese-specific list/card icons remain in use. No new runtime package is
bundled by this adaptation.

Both sources are distributed under the MIT license, reproduced below.

Feel:

Copyright (c) 2026 diip3sh

Lucide Animated (pqoqubbw/icons):

Copyright (c) 2024-2026 pqoqubbw

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
