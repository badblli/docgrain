"""Synthetic designed pages: real text-layer words drawn over a full-page picture (WP107).

Neutral content only. Docling 2.130 reads the dotted price list over a background picture as a
`document_index` table, the shape that used to lose a whole designed menu.
"""

from io import BytesIO
from pathlib import Path

PRICE_LIST = (("Lemon Soda", "4"), ("Orange Juice", "5"), ("Mineral Water", "2"), ("Black Tea Pot", "3"),
              ("Garden Salad Bowl", "9"), ("Tomato Soup Cup", "6"), ("Apple Pie", "7"),
              ("Chocolate Cake", "8"), ("Green Tea", "3"), ("Lemonade", "5"),
              ("Sparkling Water", "3"), ("Cold Coffee", "6"))


def background_png(width: int, height: int) -> bytes:
    """A photo-like backdrop (gradient, shapes) that layout models read as a picture."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        shade = 40 + (y * 120) // height
        draw.line([(0, y), (width, y)], fill=(shade, 30 + shade // 3, 90 - shade // 4))
    for index in range(12):
        x = (index * 97) % width
        y = (index * 211) % height
        draw.ellipse([x, y, x + 140, y + 90], fill=(200 - index * 9, 120 + index * 5, 60 + index * 11))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def text_over_picture_pdf(path: Path, *, dotted: bool = True) -> Path:
    """One A5-like page: a full-page background image with a real text-layer price list on top."""
    import pymupdf

    with pymupdf.open() as pdf:
        page = pdf.new_page(width=420, height=595)
        page.insert_image(page.rect, stream=background_png(840, 1190))
        page.insert_text((48, 60), "Example Drinks List", fontsize=18)
        for number, (name, price) in enumerate(PRICE_LIST, 1):
            y = 64 + number * 36
            if dotted:
                page.insert_text((48, y), f"{number}. {name} " + "." * 40, fontsize=11)
                page.insert_text((330, y), f"{price} EUR", fontsize=11)
            else:
                page.insert_text((48, y), f"{number}- {name}", fontsize=12)
                page.insert_text((340, y), f"{price} EUR", fontsize=12)
        pdf.save(path)
    return path
