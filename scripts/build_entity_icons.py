"""Generate one icon file per platform colour for Places, Organizations and Persons.

WHY A SCRIPT AND NOT THREE FILES
--------------------------------
A Cytoscape `background-image` cannot be tinted, so every glyph needs a file per
platform colour — 10 files per kind. Hand-writing 30 near-identical SVGs would drift.
This script is the single source for all of them, and re-running it is idempotent.

The three sources have different shapes (stroke-only, fill paths, a CSS class), so each
is normalised here rather than in the output: the house pattern is a 24x24 wrapper with
the fill baked into the paths, matching `app/static/icons/person-*.svg`.

Run: python scripts/build_entity_icons.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICONS = ROOT / "app" / "static" / "icons"

# The same table as `PLATFORM_COLORS` in `app/ui/src/config/nodeTypes.js`. Duplicated
# deliberately: this runs in Python at build time and cannot import the UI's JS, the
# same duplication `writer.PLATFORM_TITLE_LABELS` already carries.
PLATFORM_COLORS = {
    "messenger": "#3b6fd4",
    "telegram": "#3fb6b0",
    "whatsapp": "#4caf50",
    "linkedin": "#5cc8f0",
    "email": "#d9534f",
    "gmail": "#d9534f",
    "imap": "#d9534f",
    "outlook": "#8b5cf6",
    "sms": "#b8912a",
}

# One file per distinct colour, not per platform: the platforms that share a hex share
# a file, exactly as `PERSON_ICONS` does (`email`/`gmail`/`imap` -> `person-email.svg`).
SHARED = {"gmail": "email", "imap": "email"}

# A merged entity spans several platforms, so any platform hue would be a lie. Places
# take DARK GREY (requested); the other kinds keep the neutral grey the Correspondent
# glyph uses, which `person-merged.svg` already establishes.
MERGED_COLORS = {
    # Two shades lighter than the original `#5a5f66`: on a near-black canvas that grey
    # read as "disabled" rather than neutral. Kept BELOW the Correspondent grey
    # (`#8a97a8`) so a merged Place still reads as the weaker claim of the two.
    "place": "#9aa3ad",
    "organization": "#8a97a8",
    "person": "#8a97a8",
    # The extracted `Person` glyph, kept apart from the Correspondent's `person-*`
    # files so the two kinds never share artwork.
    "person-extracted": "#8a97a8",
    # Product is the one merged entity that takes BLUE, not grey or yellow. It is the
    # rarer, more deliberate find of the four, and the glow already says "merged" — a
    # second grey glyph would read as "a weaker Place", which it is not.
    "product": "#4c8dff",
}


def _strip_svg(raw: str) -> str:
    """The inner markup of a source SVG, with declarations and comments removed."""
    raw = re.sub(r"<\?xml.*?\?>", "", raw, flags=re.S)
    raw = re.sub(r"<!DOCTYPE.*?>", "", raw, flags=re.S)
    raw = re.sub(r"<!--.*?-->", "", raw, flags=re.S)
    start = raw.find("<svg")
    end = raw.rfind("</svg>")
    return raw[start:end]


def _viewbox(inner: str) -> str:
    match = re.search(r'viewBox="([^"]+)"', inner)
    return match.group(1) if match else "0 0 24 24"


def _body(inner: str, fill: str) -> str:
    """Every drawable element, with the fill forced.

    A `<style>` block is dropped rather than rewritten: a class rule would beat an
    inline `fill` attribute, so the one source that uses classes has its paths given
    the fill directly.
    """
    body = re.sub(r"<style.*?</style>", "", inner, flags=re.S)
    body = body[body.find(">") + 1:]           # drop the opening <svg ...>
    body = body[:body.rfind("</svg>")] if "</svg>" in body else body

    # An invisible full-canvas spacer rect (`fill="#FFFFFF" fill-opacity="0.01"`) is
    # scaffolding from the SVG Repo export, not artwork. Tinting it would paint the
    # whole glyph box; dropping it is the only correct move.
    body = re.sub(r'<\w+[^>]*fill-opacity="0\.[01]+"[^>]*/?>', "", body)

    # Stroke-only artwork (this cube, `map-pin-alt`) keeps its STROKES. It must not be
    # converted to fill: the design is an outline PLUS interior detail lines, so filling
    # every shape solid produces a plate with solid bars on it — the detail is there but
    # the same colour as the face, so nothing reads as a line. Recolouring the stroke is
    # both correct and much simpler.
    #
    # The test looks at the DRAWABLE elements, not at `body`: every SVG Repo export wraps
    # its content in `<g fill="none" stroke="none">`, so a substring test on the whole
    # body always finds a `fill=` and wrongly takes the filled branch.
    elements = re.findall(r"<(?:path|line|polygon|polyline|rect|circle|ellipse|g)\b[^>]*>", body)
    strokes = [el for el in elements if 'stroke="#' in el]
    if strokes and not any('fill="#' in el for el in elements if not _is_spacer(el)):
        body = re.sub(r'stroke="#[0-9a-fA-F]{3,8}"', f'stroke="{fill}"', body)
        # `stroke-width` is scaled UP: this artwork is drawn for 800px and lands on a
        # node a few dozen pixels across, where a 1.5px stroke would be sub-pixel.
        body = re.sub(
            r'stroke-width="([0-9.]+)"',
            lambda m: f'stroke-width="{float(m.group(1)) * _STROKE_WEIGHT:g}"',
            body,
        )
        # `linecap`/`linejoin` are kept deliberately: they are what makes the corners of
        # an outline join cleanly, and round caps are what stop the interior lines
        # ending in a blunt notch.
        return body

    # `fill="none"` is structural (a group wrapper), so it must survive.
    body = re.sub(r'fill="#[0-9a-fA-F]{3,8}"', f'fill="{fill}"', body)
    body = re.sub(r'fill="(?!none)[a-zA-Z]+"', f'fill="{fill}"', body)
    # **Non-graphic elements are dropped.** `<title>`, `<desc>` and `<defs>` carry no
    # artwork, and a `<g>` that inherits its fill is only honoured reliably when the
    # colour is on the shape itself — some rasterisers (Cytoscape's background-image
    # among them) draw the image through a canvas and disagree about inheritance across
    # a nested `<g>` carrying editor metadata.
    body = re.sub(r"<title[^>]*>.*?</title>", "", body, flags=re.S)
    body = re.sub(r"<desc[^>]*>.*?</desc>", "", body, flags=re.S)
    body = re.sub(r"<defs[^>]*>.*?</defs>", "", body, flags=re.S)
    # Editor namespaces (`sketch:type`) mean nothing to a rasteriser and some parsers
    # reject an undeclared prefix outright.
    body = re.sub(r'\s+sketch:[a-zA-Z]+="[^"]*"', "", body)
    # Every drawable shape gets the colour explicitly, so no shape depends on inheriting
    # through a wrapper the export left as `fill="none"`.
    body = re.sub(
        r"<(path|polygon|rect|circle|ellipse)\b([^>]*?)/?>",
        lambda m: m.group(0)
        if 'fill="' in m.group(2)
        else f'<{m.group(1)}{m.group(2)} fill="{fill}"/>',
        body,
    )
    # Anything with no explicit fill inherits from the wrapping <g>.
    return f'<g fill="{fill}">{body}</g>'


def _is_spacer(element: str) -> bool:
    """A full-canvas rect with near-zero opacity, left over from the export."""
    return 'fill-opacity="0.' in element


# Multiplier on stroke-artwork's drawn width. These sources are authored for 800px and
# land on a node ~30px across; a 1.5px stroke would be sub-pixel at that size, so the
# outline would vanish entirely and the glyph would be invisible.
_STROKE_WEIGHT = 1.6


def build(kind: str, source: Path) -> None:
    # The source art is NOT committed (`.tmp_*.svg` is gitignored), so on a fresh clone
    # only the generated files exist. Skipping an absent source lets one kind be
    # regenerated alone — `build("place", …)` must not die on a missing `.tmp_org.svg`.
    if not source.exists():
        print(f"{kind}: skipped — source {source.name} not present")
        return
    raw = source.read_text(encoding="utf-8")
    inner = _strip_svg(raw)
    viewbox = _viewbox(inner)

    written = []
    for platform, colour in {**PLATFORM_COLORS, "merged": MERGED_COLORS[kind]}.items():
        name = SHARED.get(platform, platform)
        target = ICONS / f"{kind}-{name}.svg"
        if target.exists() and platform in SHARED:
            continue
        # `merged` is its own file; the shared alias never applies to it.
        body = _body(inner, colour)
        target.write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            f"<!-- {kind}, {platform} — generated by scripts/build_entity_icons.py from\n"
            f"     {source.name} (svgrepo). Normalised to a 24x24 wrapper so every icon\n"
            f"     draws at the same weight as the platform glyphs. The fill is baked in,\n"
            f"     because a Cytoscape background-image cannot be tinted. -->\n"
            f'<svg width="24" height="24" viewBox="{viewbox}" fill="none" '
            'xmlns="http://www.w3.org/2000/svg">\n'
            f"{body}\n"
            "</svg>\n",
            encoding="utf-8",
        )
        written.append(target.name)

    print(f"{kind}: {len(written)} files -> {', '.join(sorted(set(written)))}")


if __name__ == "__main__":
    # `scripts/icons_src/` holds a committed copy of any source whose download is gone.
    # `.tmp_*` is the original convention and wins if present (a fresh download).
    def source(tmp: str, keep: str) -> Path:
        tmp_path = ROOT / tmp
        return tmp_path if tmp_path.exists() else ROOT / "scripts" / "icons_src" / keep

    build("place", source(".tmp_pin.svg", "place.svg"))
    build("organization", source(".tmp_org.svg", "organization.svg"))
    build("person-extracted", source(".tmp_person.svg", "person.svg"))
    build("product", source(".tmp_product.svg", "product.svg"))
