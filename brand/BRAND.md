# Ronda brand

> Your agents work all night. Ronda keeps watch.
> *Agen kerja, Ronda jaga.*

Ronda is named for *ronda malam*, the neighbourhood night watch in Indonesia: neighbours take turns
keeping guard while the others sleep, and strike the *kentongan* (a bamboo slit drum) when something
needs attention. Agents work for hours; Ronda keeps watch and only calls you when you are needed.

## Logo

The mark is a simplified kentongan: a vertical capsule with one horizontal slot. It also reads as a
notification badge. The wordmark is "ronda", lowercase, JetBrains Mono ExtraBold, outlined.

| File | Use |
| --- | --- |
| `logo/lockup-on-dark.svg` | Default. Amber mark, light wordmark, on Malam or any dark ground |
| `logo/lockup-on-light.svg` | Single colour Malam, on light grounds |
| `logo/mark.svg` | Amber mark alone (badges, avatars, small spaces) |
| `logo/mark-light.svg`, `logo/mark-dark.svg` | One-colour marks |
| `logo/wordmark-light.svg`, `logo/wordmark-dark.svg` | Wordmark alone |
| `logo/icon.svg`, `logo/icon-{32,192,512}.png` | App icon and favicon: amber mark on a Malam square |
| `social/social-preview.png` | GitHub social preview, 1280 x 640 |
| `social/readme-banner.png` | README header, 2560 x 640 (shown at 1280 x 320) |

- Clear space around the lockup: the width of the mark on every side.
- Smallest sizes: lockup 96px wide, mark 12px tall, icon 16px.
- Do not recolour the mark outside the palette, add effects, rotate it, or set "ronda" in another face.
- The slot is cut out, so the mark works on any ground. Keep the slot horizontal.

## Colour

| Name | Hex | Role |
| --- | --- | --- |
| Malam | `#14162B` | Background. Ronda is dark-first |
| Lentera | `#F2A93B` | Accent, and the colour of "needs you" (`waiting_approval`, `waiting_input`) |
| Bambu | `#C9B27C` | Secondary: the Indonesian tagline, code keywords |
| Hijau | `#3FB37F` | `running` |
| Merah | `#E5484D` | `error` (UI text uses a lifted tint for contrast, see `design.md`) |
| Abu | `#8B8FA3` | `done`, `ended`, idle, muted text |

Amber is a signal, not a decoration: on any screen it marks only what needs the user, plus one
primary action. Status is always a word in its colour, never colour alone.

## Type

- **JetBrains Mono** 800 for headings and the wordmark; 400 for code, paths, branches, env vars, times.
- **Inter** 400 and 600 for everything else.
- Sentence case everywhere. No tracked capitals.

## Voice

Calm and brief. Ronda only speaks when there is something to do.

- Say what happened and what to do: "The hub is not answering. Start it with `ronda up`."
- Use the product's nouns: session, agent, hook, pos, hub. Never "seamless", "supercharge", "unlock".
- English in the UI. The Indonesian names are flavour for the docs:
  - *Kentongan*: notifications
  - *Pos*: an adapter for one platform (a pos ronda is the watch post)
  - *Warga*: the daemon

## Where it lives

- Tokens and rules: `design.md`, `site/tokens.css`
- Shared inbox components: `site/inbox.css`
- Landing page: `site/index.html`; inbox design direction: `site/inbox.html`
- Logo generator inputs: JetBrains Mono ExtraBold (OFL 1.1), outlined to paths
