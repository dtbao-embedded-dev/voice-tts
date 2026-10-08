"""The app icon: a white sound wave on a black disc - the app is black and white.

One geometry feeds every surface, so they cannot drift apart: the tray and the
window/exe ``.ico`` are drawn from it with Pillow, the web favicon is the same
shapes as SVG. ``svg()`` needs only the standard library, so the server-only
build and the Docker image (no Pillow, no tray) still serve the favicon.
"""

from __future__ import annotations

from pathlib import Path

BARS = (0.28, 0.55, 0.85, 0.55, 0.28)  # bar heights, as a fraction of 0.6 x size
ICO_SIZES = (16, 20, 24, 32, 48, 64, 256)  # 20: the title bar at 125 % scaling
BLACK = (0, 0, 0, 255)
WHITE = (255, 255, 255, 255)


def geometry(size: int) -> tuple[tuple[float, float, float, float], int, list[tuple[float, ...]]]:
    """``(disc box, ring width, bars)`` for a ``size`` x ``size`` square.

    The disc box is the ring's outer edge; each bar is ``(x0, y0, x1, y1, radius)``,
    end-exclusive, with the radius making it a pill.

    Bars sit on whole pixels, each at least 1 px wide with at least a 1 px gap:
    at 16 px a fractional layout puts 1.2 px bars 0.8 px apart, and the
    rasteriser merges them into one white blob.
    """
    disc = (1, 1, size - 2, size - 2)
    ring = max(2, size // 24) if size >= 24 else 1
    step = size / (len(BARS) + 3)
    width = max(1, round(step * 0.6))
    gap = max(1, round(step * 0.4))
    left = (size - (len(BARS) * width + (len(BARS) - 1) * gap)) // 2
    bars = []
    for i, height in enumerate(BARS):
        tall = max(width, round(height * size * 0.6))
        tall += (size - tall) % 2  # same parity as size, so the bar is centred
        x0, y0 = left + i * (width + gap), (size - tall) // 2
        bars.append((x0, y0, x0 + width, y0 + tall, width / 2))
    return disc, ring, bars


def image(size: int = 64):
    """The icon as an RGBA Pillow image, drawn natively at ``size``."""
    from PIL import Image, ImageDraw

    disc, ring, bars = geometry(size)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(out)
    draw.ellipse(disc, fill=BLACK, outline=WHITE, width=ring)
    for x0, y0, x1, y1, radius in bars:
        # Pillow's box is end-inclusive; a bar under 3 px is too thin to round.
        draw.rounded_rectangle((x0, y0, x1 - 1, y1 - 1), radius=radius if x1 - x0 >= 3 else 0,
                               fill=WHITE)
    return out


def svg(size: int = 64) -> str:
    """The same icon as an SVG document, for the web favicon."""
    disc, ring, bars = geometry(size)
    # SVG strokes straddle the outline; Pillow's ring lies inside it.
    cx = (disc[0] + disc[2] + 1) / 2
    r = (disc[2] - disc[0] + 1) / 2 - ring / 2
    shapes = [f'<circle cx="{cx:g}" cy="{cx:g}" r="{r:g}" fill="#000" '
              f'stroke="#fff" stroke-width="{ring}"/>']
    shapes += [f'<rect x="{x0:.2f}" y="{y0:.2f}" width="{x1 - x0:.2f}" height="{y1 - y0:.2f}" '
               f'rx="{radius:.2f}" fill="#fff"/>' for x0, y0, x1, y1, radius in bars]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}">'
            + "".join(shapes) + "</svg>")


def save_ico(path: str | Path) -> Path:
    """Write a Windows ``.ico`` holding every size in ``ICO_SIZES``.

    Each size is drawn at its own resolution rather than scaled down from the
    largest, so the ring stays a crisp line at 16 px.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    largest, *rest = [image(s) for s in sorted(ICO_SIZES, reverse=True)]
    largest.save(path, format="ICO", sizes=[(s, s) for s in ICO_SIZES], append_images=rest)
    return path
