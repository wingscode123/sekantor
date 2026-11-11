# Design: Ronda

The locked system. Every Hallmark run reads this first and pages share it. Change it on purpose; the file is the rule.
Brand source: `docs/PRD.md` (Identitas visual). Guidelines for people: `brand/BRAND.md`.

## System
- Genre: modern-minimal
- Shape of the first page: custom (night inbox); the product screen is an app screen
- Theme: brand (vibe: "night watch, lantern amber, terminal calm")
- Axes: dark/mono/warm · posture: restrained (amber only where an agent waits, plus the one primary control)

## Tokens
`site/tokens.css` is the source of truth. The roles:
```css
:root {
  --color-paper: oklch(21% 0.041 278);   /* Malam #14162B */
  --color-paper-2: oklch(24.5% 0.042 278);  --color-paper-3: oklch(28.5% 0.042 278);
  --color-ink: oklch(95% 0.012 278);  --color-ink-2: oklch(83% 0.022 278);  --color-muted: oklch(68% 0.03 277);  --color-rule: oklch(34% 0.038 278);
  --color-accent: oklch(78.7% 0.147 73); /* Lentera #F2A93B */  --color-accent-ink: oklch(21% 0.041 278);  --color-focus: oklch(81% 0.16 73);
  --color-bambu: oklch(77% 0.076 87.5);  /* Bambu #C9B27C, secondary: code keywords, the Indonesian tagline */
  --color-running: oklch(68.8% 0.13 160.3); /* #3FB37F */  --color-waiting: var(--color-accent);
  --color-failing: oklch(70% 0.17 23);   /* #E5484D lifted for 4.5:1 on paper-3 */  --color-idle: var(--color-muted); /* #8B8FA3 */
  --font-display: "JetBrains Mono", ui-monospace, monospace;  --font-body: "Inter", ui-sans-serif, system-ui, sans-serif;  --font-mono: var(--font-display);
  --radius-card: 8px;  --radius-control: 6px;  --rule-hair: 1px;  --shadow-card: none;
}
```
The spacing scale, the type scale, the easings and the durations are the scaffold's and live in `site/tokens.css`.

## Rules
- Status is a word in its colour (`site/inbox.css` `.status--*`), never a dot and never colour alone.
- A session that needs you is the only lit card: `card--lit`, amber 1px edge. Nothing else on screen is amber except the single primary control.
- Headings in JetBrains Mono 800, tracking -0.03em; everything else Inter 400/600. Mono also for code, paths, branches, env vars and times.
- Labels sentence case, untracked. No eyebrows, no middle-dot strings, no gradients, no glow.

## Controls
- Primary (site): amber fill, Malam text, 6px radius, 48px.
- Product controls (`.ctl`): outlined, 34px with a 44px hit target; the go action has an amber edge and amber text.

## Motion
- Character: still. Colour steps on hover at 220ms; no reveals; loaders only. Under reduced motion everything ends at once.

## Exports
`site/tokens.css` in this project. The M1 web UI (`web/`) imports it and `site/inbox.css`.
