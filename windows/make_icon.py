"""Draws AceList's icon, an old analog TV, and saves it as `.ico` and favicon.

Run it after changing the drawing: `python windows/make_icon.py` (needs Pillow, from
the `build` extra). The results are committed, so building never needs Pillow.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
ICON = ROOT / "windows" / "acelist.ico"
FAVICON = ROOT / "app" / "web" / "static" / "favicon.ico"
PREVIEW = ROOT / "windows" / "acelist.png"

SIZE = 1024  # drawn large, then scaled down for smooth edges
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

WOOD = (122, 74, 42)
WOOD_DARK = (84, 49, 27)
WOOD_LIGHT = (156, 102, 62)
BEZEL = (36, 38, 44)
SCREEN_TOP = (120, 196, 214)
SCREEN_BOTTOM = (40, 92, 132)
METAL = (196, 200, 206)
KNOB = (226, 212, 180)
KNOB_DARK = (120, 104, 78)


def _gradient(size: tuple[int, int], top: tuple, bottom: tuple) -> Image.Image:
    width, height = size
    image = Image.new("RGB", size)
    pixels = image.load()
    for y in range(height):
        t = y / max(height - 1, 1)
        color = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom, strict=True))
        for x in range(width):
            pixels[x, y] = color
    return image


def draw() -> Image.Image:
    s = SIZE
    image = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)

    # Antennas: a V of thin rods from a small base.
    base = (s * 0.5, s * 0.25)
    for tip in ((s * 0.27, s * 0.04), (s * 0.73, s * 0.06)):
        d.line([base, tip], fill=METAL, width=round(s * 0.028))
        d.ellipse(
            [tip[0] - s * 0.03, tip[1] - s * 0.03, tip[0] + s * 0.03, tip[1] + s * 0.03],
            fill=METAL,
        )
    d.ellipse([s * 0.42, s * 0.2, s * 0.58, s * 0.3], fill=BEZEL)

    # Legs.
    for x in (0.2, 0.74):
        d.rounded_rectangle(
            [s * x, s * 0.84, s * (x + 0.06), s * 0.96], radius=s * 0.02, fill=WOOD_DARK
        )

    # Wooden cabinet with a lighter top edge.
    body = [s * 0.06, s * 0.27, s * 0.94, s * 0.88]
    d.rounded_rectangle(body, radius=s * 0.08, fill=WOOD_DARK)
    d.rounded_rectangle(
        [body[0] + s * 0.012, body[1] + s * 0.008, body[2] - s * 0.012, body[3] - s * 0.02],
        radius=s * 0.075,
        fill=WOOD,
    )
    d.rounded_rectangle(
        [body[0] + s * 0.05, body[1] + s * 0.012, body[2] - s * 0.05, body[1] + s * 0.035],
        radius=s * 0.012,
        fill=WOOD_LIGHT,
    )

    # Screen: dark bezel, then a rounded CRT face with a gradient and a glare.
    bezel = [s * 0.12, s * 0.33, s * 0.7, s * 0.82]
    d.rounded_rectangle(bezel, radius=s * 0.09, fill=BEZEL)
    face_box = [s * 0.155, s * 0.365, s * 0.665, s * 0.785]
    face_size = (round(face_box[2] - face_box[0]), round(face_box[3] - face_box[1]))
    face = _gradient(face_size, SCREEN_TOP, SCREEN_BOTTOM).convert("RGBA")
    mask = Image.new("L", face_size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, face_size[0] - 1, face_size[1] - 1], radius=s * 0.075, fill=255
    )
    image.paste(face, (round(face_box[0]), round(face_box[1])), mask)
    glare = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(glare).ellipse([s * 0.2, s * 0.39, s * 0.44, s * 0.52], fill=(255, 255, 255, 90))
    image.alpha_composite(glare.filter(ImageFilter.GaussianBlur(s * 0.02)))

    # Control panel: two knobs and a speaker grille.
    for cy in (0.44, 0.58):
        cx = 0.82
        r = 0.055
        d.ellipse([s * (cx - r), s * (cy - r), s * (cx + r), s * (cy + r)], fill=KNOB_DARK)
        r2 = 0.042
        d.ellipse([s * (cx - r2), s * (cy - r2), s * (cx + r2), s * (cy + r2)], fill=KNOB)
        d.line([(s * cx, s * (cy - r2)), (s * cx, s * cy)], fill=KNOB_DARK, width=round(s * 0.012))
    for i in range(4):
        y = s * (0.69 + i * 0.03)
        d.line([(s * 0.76, y), (s * 0.88, y)], fill=WOOD_DARK, width=round(s * 0.012))
    return image


def main() -> None:
    image = draw()
    largest = image.resize((256, 256), Image.LANCZOS)
    largest.save(ICON, sizes=ICO_SIZES)
    largest.save(FAVICON, sizes=[(16, 16), (32, 32), (48, 48)])
    largest.save(PREVIEW)
    print(f"wrote {ICON}, {FAVICON} and {PREVIEW}")


if __name__ == "__main__":
    main()
