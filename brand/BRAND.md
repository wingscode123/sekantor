# SeKantor brand

> Your AI agents, in one office.

The Indonesian expression *se-kantor* means sharing an office or being officemates. SeKantor brings the AI coding agents on your machine into a shared pixel-art office. Each agent gets a desk and an avatar.

The mark is a small office building. Lit windows represent agents at work, with a coral antenna light on the roof, a walnut-toned entry and a teal ground line. The building uses a 16 × 16 pixel grid. Monochrome versions use cutouts for the windows and door.

## Palette

The brand borrows the warm wood, apricot plaster and petrol blue of the office sprites. Use these colours in the mark and brand graphics.

| Colour | Hex | Role |
| --- | --- | --- |
| Ink | `#332B35` | Building silhouette, light-surface text, dark brand surface |
| Slate | `#51444C` | Unlit windows and dusk shadows |
| Walnut | `#70483D` | Shaded timber and secondary office façades |
| Wood | `#BD8968` | Door, window frames and pavement details |
| Apricot | `#E5BB9F` | Icon tile and warm architectural trim |
| Gold | `#F7CE82` | Lit windows and dark-surface wordmark accent |
| Cream | `#FFF0CE` | Dark-surface text and monochrome mark |
| Paper | `#FFF8EC` | Light brand surface |
| Coral | `#EF8B72` | Antenna light |
| Petrol | `#2D5558` | Light-surface wordmark accent and featured office façade |
| Teal | `#51817C` | Ground line and decorative accents |
| Glass | `#87AEAD` | Cool sky details |

Set light-surface text in Ink or Petrol on Paper. Set dark-surface text in Cream or Gold on Ink. Each pairing exceeds 4.5:1. Reserve the remaining colour combinations for illustration, and check contrast again when introducing another text background.

## Type

The wordmark spells **SeKantor** in a custom pixel alphabet. The colour versions highlight **Kantor** in Petrol on light surfaces and Gold on dark surfaces. The social graphics use the same pixel alphabet for the tagline. Use Inter for UI and body copy and JetBrains Mono for compact headings, code, paths and other fixed-width details.

## Files

| File | Use |
| --- | --- |
| `logo/mark.svg` | Full-colour building on a light surface |
| `logo/mark-light.svg`, `logo/mark-dark.svg` | One-colour building in Cream or Ink |
| `logo/wordmark-light.svg`, `logo/wordmark-dark.svg` | Wordmark alone. Light lettering is for dark surfaces and dark lettering is for light surfaces |
| `logo/lockup-on-dark.svg`, `logo/lockup-on-light.svg` | Building and wordmark together, named for the background |
| `logo/icon.svg` | App icon and web favicon on a rounded Apricot tile |
| `logo/icon-32.png`, `logo/icon-192.png`, `logo/icon-512.png` | Raster icons with transparent corners. The desktop icon script uses the 512 px export |
| `social/social-preview.png` | 1280 × 640 link preview |
| `social/readme-banner.png` | 2560 × 640 repository banner |

Run `python brand/build.py` from the repository root with Python 3.11 to regenerate the kit and update the copies in `web/public`.

## Placement

- Leave clear space of at least one quarter of the mark's height around the mark, lockup and icon. For the standalone wordmark, use at least half its cap height.
- Use at least 16 px for the standalone mark, 24 px tall for the lockup and 14 px cap height for the standalone wordmark. Use the tile at 32 px or larger when the full window pattern needs to read.
- Preserve the aspect ratio. Use integer multiples of the source grid when the layout allows, and use nearest-neighbour scaling for raster assets.
- Choose the lockup for the surface and leave the art clear of busy imagery. Avoid stretching, smoothing, outlines, shadows and recolouring individual windows.
