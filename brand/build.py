"""Build the SeKantor brand assets with Python 3.11 and the standard library."""
from pathlib import Path
import struct
import zlib


BRAND = Path(__file__).resolve().parent
PALETTE = {
    "ink": "#332B35",
    "slate": "#51444C",
    "walnut": "#70483D",
    "wood": "#BD8968",
    "apricot": "#E5BB9F",
    "gold": "#F7CE82",
    "cream": "#FFF0CE",
    "paper": "#FFF8EC",
    "coral": "#EF8B72",
    "petrol": "#2D5558",
    "teal": "#51817C",
    "glass": "#87AEAD",
}
NAME = "SeKantor"
TAGLINE = "Your AI agents, in one office."

MARK = (
    (10, 0, 1, 1, "coral"),
    (10, 1, 1, 1, "ink"),
    (2, 2, 12, 1, "ink"),
    (3, 3, 10, 12, "ink"),
    (5, 4, 2, 2, "gold"),
    (9, 4, 2, 2, "slate"),
    (5, 7, 2, 2, "gold"),
    (9, 7, 2, 2, "gold"),
    (5, 10, 2, 1, "slate"),
    (9, 10, 2, 1, "gold"),
    (7, 12, 2, 3, "wood"),
    (1, 15, 14, 1, "teal"),
)

# Slashes separate rows. Short glyphs sit on the seventh-row baseline,
# with a further row available for descenders and the comma.
FONT = {
    "S": "01111/10000/10000/01110/00001/00001/11110",
    "K": "10001/10010/10100/11000/10100/10010/10001",
    "Y": "10001/10001/01010/00100/00100/00100/00100",
    "A": "01110/10001/10001/11111/10001/10001/10001",
    "I": "111/010/010/010/010/010/111",
    "a": "0110/0001/0111/1001/0111",
    "c": "0111/1000/1000/1000/0111",
    "e": "0110/1001/1111/1000/0111",
    "f": "011/100/100/111/100/100/100",
    "g": "0111/1001/1001/0111/0001/1110",
    "i": "1/0/1/1/1/1/1",
    "n": "1110/1001/1001/1001/1001",
    "o": "0110/1001/1001/1001/0110",
    "r": "101/110/100/100/100",
    "s": "0111/1000/0110/0001/1110",
    "t": "010/010/111/010/010/010/001",
    "u": "1001/1001/1001/1001/0111",
    " ": "00",
    ",": "01/01/10",
    ".": "1",
}


class Canvas:
    def __init__(self, width, height, fill=None):
        self.width = width
        self.height = height
        self.rows = [[fill] * width for _ in range(height)]

    def rect(self, x, y, width, height, fill):
        left, right = max(0, x), min(self.width, x + width)
        if left < right:
            for row in self.rows[max(0, y):max(0, y + height)]:
                row[left:right] = [fill] * (right - left)

    def place(self, image, x, y, scale=1):
        for left, top, width, height, fill in image.rectangles():
            self.rect(x + left * scale, y + top * scale,
                      width * scale, height * scale, fill)

    def rectangles(self):
        """Merge horizontal colour runs and extend identical runs downwards."""
        active = {}
        for y, row in enumerate(self.rows + [[None] * self.width]):
            next_active = {}
            start = 0
            for x in range(1, self.width + 1):
                if x == self.width or row[x] != row[start]:
                    fill = row[start]
                    if fill is not None:
                        run = (start, x - start, fill)
                        next_active[run] = active.pop(run, y)
                    start = x
            for (left, width, fill), top in active.items():
                yield left, top, width, y - top, fill
            active = next_active


def building(monochrome=None):
    image = Canvas(16, 16)
    for x, y, width, height, fill in MARK:
        if monochrome:
            fill = None if fill in ("gold", "slate", "wood") else monochrome
        image.rect(x, y, width, height, fill)
    return image


def pixel_text(message, fill, accent=None):
    glyphs = [FONT[char].split("/") for char in message]
    image = Canvas(sum(len(glyph[0]) + 1 for glyph in glyphs) - 1, 8)
    x = 0
    for index, (char, glyph) in enumerate(zip(message, glyphs)):
        baseline = 7 if char in "g," else 6
        top = baseline - len(glyph) + 1
        colour = accent if accent and index >= 2 else fill
        for dy, row in enumerate(glyph):
            for dx, pixel in enumerate(row):
                if pixel == "1":
                    image.rect(x + dx, top + dy, 1, 1, colour)
        x += len(glyph[0]) + 1
    return image


def lockup(dark_background):
    wordmark = pixel_text(NAME, "cream" if dark_background else "ink",
                          "gold" if dark_background else "petrol")
    image = Canvas(20 + wordmark.width, 16)
    image.place(building("cream" if dark_background else None), 0, 0)
    image.place(wordmark, 20, 5)
    return image


def app_icon():
    image = Canvas(32, 32)
    insets = (5, 3, 2, 1, 1) + (0,) * 22 + (1, 1, 2, 3, 5)
    for y, inset in enumerate(insets):
        image.rect(inset, y, 32 - inset * 2, 1, "apricot")
    image.place(building(), 8, 8)
    return image


def draw_office(scene, x, street, width, height, featured=False):
    """Draw a street-facing office with inset windows and a walnut entry."""
    roof = street - height
    scene.rect(x + 4, street, width + 6, 2, "ink")
    scene.rect(x, roof, width, height, "petrol" if featured else "walnut")
    scene.rect(x + width - 5, roof, 5, height, "ink")
    scene.rect(x - 2, roof, width + 4, 2, "apricot" if featured else "wood")
    scene.rect(x - 2, roof + 2, width + 4, 1, "ink")
    for row, y in enumerate(range(roof + 6, street - 14, 7)):
        for column, left in enumerate(range(x + 4, x + width - 9, 8)):
            lit = (column + row * 2) % 4 != 1
            scene.rect(left - 1, y - 1, 7, 6, "ink")
            scene.rect(left, y, 5, 4, "gold" if lit else "slate")
            scene.rect(left + 2, y, 1, 4, "wood" if lit else "ink")
            if lit:
                scene.rect(left, y + 3, 5, 1, "wood")
    door = x + width // 2 - 4
    scene.rect(door - 2, street - 10, 11, 10, "ink")
    scene.rect(door, street - 8, 7, 8, "walnut")
    scene.rect(door + 1, street - 7, 5, 4, "gold" if featured else "slate")
    scene.rect(door + 5, street - 2, 1, 1, "apricot")
    scene.rect(door - 3, street, 13, 1, "wood")
    if featured:
        scene.rect(x + width - 12, roof - 6, 1, 6, "ink")
        scene.rect(x + width - 12, roof - 7, 1, 1, "coral")


def social(width):
    """Compose on a four-pixel grid, with extra street frontage on the banner."""
    scene = Canvas(width, 160, "ink")
    scene.rect(0, 103, width, 24, "walnut")
    scene.rect(0, 127, width, 33, "petrol")
    scene.rect(0, 127, width, 1, "apricot")
    scene.rect(0, 133, width, 2, "ink")
    scene.rect(0, 135, width, 25, "slate")
    for x in range(5, width, 23):
        scene.rect(x, 147, 10, 1, "wood")

    # Low, quiet shapes across the horizon behind the detailed office frontage.
    for x in range(-9, width, 23):
        height = 9 + (x % 7) * 2
        scene.rect(x, 114 - height, 19, height, "slate")
        scene.rect(x + 4, 111 - height, 10, 3, "slate")

    if width == 320:
        text_x, text_y, logo_scale = 24, 28, 2
        featured_x = 67
        buildings = [(28, 27, 25), (67, 42, 40), (125, 34, 25),
                     (188, 33, 29), (237, 43, 39), (293, 30, 22)]
    else:
        text_x, text_y, logo_scale = 46, 38, 3
        featured_x = 434
        buildings = [(8, 27, 26), (44, 35, 22), (102, 43, 24),
                     (162, 34, 22), (244, 34, 21), (311, 41, 37),
                     (368, 53, 61), (434, 66, 81), (518, 43, 51),
                     (576, 42, 37), (630, 36, 25)]

    for x, span, height in buildings:
        draw_office(scene, x, 124, span, height, featured=x == featured_x)

    # Streetlights, pools of pavement light and a few sky pixels.
    for x in ((14, 174, 282) if width == 320 else (89, 293, 428, 566, 625)):
        scene.rect(x - 4, 124, 10, 1, "wood")
        scene.rect(x, 110, 1, 14, "ink")
        scene.rect(x - 1, 110, 4, 2, "gold")
    for x, y in ((17, 18), (145, 17), (214, 24), (281, 14), (379, 23),
                 (446, 15), (510, 21), (590, 24), (619, 15)):
        scene.rect(x, y, 1, 1, "glass")

    logo = lockup(True)
    tagline = pixel_text(TAGLINE, "cream")
    tagline_y = text_y + logo.height * logo_scale + 4
    scene.place(logo, text_x, text_y, logo_scale)
    scene.place(tagline, text_x, tagline_y)
    return scene


def write_svg(path, image):
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {image.width} {image.height}"'
        f' width="{image.width}" height="{image.height}" shape-rendering="crispEdges"'
        ' role="img" aria-labelledby="title">',
        f'  <title id="title">{NAME}</title>',
    ]
    for x, y, width, height, fill in image.rectangles():
        lines.append(f'  <rect x="{x}" y="{y}" width="{width}" height="{height}"'
                     f' fill="{PALETTE[fill]}"/>')
    path.write_bytes(("\n".join(lines) + "\n</svg>\n").encode("utf-8"))


def png_chunk(kind, data):
    return (struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data)))


def write_png(path, image, scale):
    colours = {name: bytes.fromhex(value[1:]) + b"\xff" for name, value in PALETTE.items()}
    colours[None] = bytes(4)
    data = bytearray()
    for row in image.rows:
        scanline = b"\0" + b"".join(colours[pixel] * scale for pixel in row)
        data.extend(scanline * scale)
    header = struct.pack(">2I5B", image.width * scale, image.height * scale, 8, 6, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", header)
                     + png_chunk(b"IDAT", zlib.compress(data, level=9))
                     + png_chunk(b"IEND", b""))


def build():
    logo = BRAND / "logo"
    graphics = BRAND / "social"
    public = BRAND.parent / "web" / "public"
    for folder in (logo, graphics, public):
        folder.mkdir(parents=True, exist_ok=True)

    icon = app_icon()
    on_dark = lockup(True)
    write_svg(logo / "mark.svg", building())
    write_svg(logo / "mark-light.svg", building("cream"))
    write_svg(logo / "mark-dark.svg", building("ink"))
    write_svg(logo / "wordmark-light.svg", pixel_text(NAME, "cream", "gold"))
    write_svg(logo / "wordmark-dark.svg", pixel_text(NAME, "ink", "petrol"))
    write_svg(logo / "lockup-on-dark.svg", on_dark)
    write_svg(logo / "lockup-on-light.svg", lockup(False))
    write_svg(logo / "icon.svg", icon)
    write_svg(public / "icon.svg", icon)
    write_svg(public / "lockup.svg", on_dark)
    for size in (32, 192, 512):
        write_png(logo / f"icon-{size}.png", icon, size // icon.width)
    write_png(graphics / "social-preview.png", social(320), 4)
    write_png(graphics / "readme-banner.png", social(640), 4)


if __name__ == "__main__":
    build()
