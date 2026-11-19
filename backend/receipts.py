"""The year's receipts of one person on A4 sheets, to print and take to the CAF (the 730 is one per tax code).

Every receipt keeps its own orientation and is set at the width of a column: three columns side by side fill the
sheet. Receipts are packed into the columns that leave the least empty space (best fit, tallest first), so a sheet
holds as many as fit; one longer than a column goes on in the next one. Under each receipt: date, amount and kind of
expense; at the top of the sheet: name, tax code, year, page.

Pages are drawn as grey images (a receipt is black on white, and grey halves the file) and saved as one PDF."""
import io
import re

from PIL import Image, ImageDraw, ImageFont, ImageOps

DPI = 200
MM = DPI / 25.4
PAGE_W, PAGE_H = round(210 * MM), round(297 * MM)      # A4
MARGIN = round(8 * MM)
HEADER = round(12 * MM)
COLS = 3
GAP = round(5 * MM)
COL_W = (PAGE_W - 2 * MARGIN - (COLS - 1) * GAP) // COLS
COL_H = PAGE_H - 2 * MARGIN - HEADER
LABEL = round(5 * MM)           # the line under a receipt
SPACE = round(4 * MM)           # between two receipts in a column
MIN_PIECE = round(25 * MM)      # a receipt is not cut leaving a sliver of it

_RECEIPT_WORDS = re.compile(r'scontrin|ricevut|ticket|receipt', re.I)


def looks_like_receipt(doc, first_page=None):
    """A receipt: said so by its type or title, a photo, or a PDF page much taller than wide (a scanned receipt)."""
    if _RECEIPT_WORDS.search(' '.join(str(doc.get(k) or '') for k in ('doc_type', 'title'))):
        return True
    if (doc.get('mime') or '').startswith('image/'):
        return True
    return bool(first_page and first_page[1] >= 1.6 * first_page[0])


def pdf_page_size(data):
    """(width, height) of the first page of a PDF, or None."""
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(data)
        try:
            return tuple(pdf[0].get_size()) if len(pdf) else None
        finally:
            pdf.close()
    except Exception:
        return None


def to_images(data, mime):
    """The pages of a document as images: a photo is one, a PDF one per page (at most 4: a receipt, not a book)."""
    if (mime or '') == 'application/pdf' or data[:5] == b'%PDF-':
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(data)
        try:
            return [pdf[i].render(scale=DPI / 72 * 0.75).to_pil() for i in range(min(len(pdf), 4))]
        finally:
            pdf.close()
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except Exception:
        pass
    img = Image.open(io.BytesIO(data))
    return [ImageOps.exif_transpose(img)]


def trim(img):
    """Grey, without the white (or almost) border a scan leaves around the paper."""
    g = img.convert('L')
    box = g.point(lambda v: 255 if v < 235 else 0).getbbox()
    if box:
        pad = round(2 * MM)
        box = (max(0, box[0] - pad), max(0, box[1] - pad), min(g.width, box[2] + pad), min(g.height, box[3] + pad))
        g = g.crop(box)
    return g


SPLIT_MIN = round(60 * MM)      # a receipt goes on into the space left at the bottom of a column only if this much is free


def pack(heights, capacity=COL_H, overhead=LABEL + SPACE, min_piece=MIN_PIECE, split_min=SPLIT_MIN):
    """The columns that hold every receipt: [[(index, top, bottom)]], a part of receipt `index` from top to bottom.

    Best fit, tallest first: a receipt goes in the column it fills best. When none has room, it goes on into the
    largest space left at the bottom of a column (if at least split_min) and the rest continues elsewhere, so the sheets
    fill up; a receipt longer than a column is cut too. No part is shorter than min_piece. Each part also takes
    `overhead` (its label and the space under it)."""
    columns = []                                        # [free, [(i, top, bottom)]]
    todo = [(heights[i], i, 0) for i in range(len(heights))]   # (rest, index, top)
    while todo:
        todo.sort(key=lambda t: (-t[0], t[1]))
        rest, i, top = todo.pop(0)
        need = rest + overhead
        fits = [c for c in columns if c[0] >= need]
        if fits:
            col = min(fits, key=lambda c: c[0])
            col[0] -= need
            col[1].append((i, top, top + rest))
            continue
        roomy = max(columns, key=lambda c: c[0], default=None)
        room = roomy[0] - overhead if roomy else 0
        if roomy is None or room < split_min or rest - room < min_piece:
            roomy = [capacity, []]
            columns.append(roomy)
            room = capacity - overhead
        part = min(rest, room)
        if 0 < rest - part < min_piece:                 # do not leave a sliver for the next column
            part = rest - min_piece
        roomy[0] -= part + overhead
        roomy[1].append((i, top, top + part))
        if rest - part:
            todo.append((rest - part, i, top + part))
    return [c[1] for c in columns]


def _font(size):
    # DejaVu (fonts-dejavu-core in the image) has the € sign; Pillow's own font does not
    for path in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/TTF/DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                       # Pillow without FreeType: the small bitmap font
        return ImageFont.load_default()


def build_pdf(receipts, title):
    """receipts: [(image, label)] in date order; title: the header of every sheet. PDF bytes."""
    images = [trim(img) for img, _ in receipts]
    images = [im.resize((COL_W, max(1, round(im.height * COL_W / im.width))), Image.LANCZOS) for im in images]
    columns = pack([im.height for im in images], COL_H + SPACE)   # the last part of a column needs no space under it
    # inside a column, in date order (the order they came in); a receipt in several parts says which one
    columns = [sorted(c) for c in columns]
    parts = {}
    for c in columns:
        for i, top, _ in c:
            parts.setdefault(i, []).append(top)
    def label_of(i, top):
        tops = sorted(parts[i])
        return receipts[i][1] if len(tops) == 1 else f'{receipts[i][1]} ({tops.index(top) + 1}/{len(tops)})'
    sheets = [columns[i:i + COLS] for i in range(0, len(columns), COLS)] or [[]]
    head, small = _font(round(3.6 * MM)), _font(round(2.7 * MM))
    pages = []
    for n, sheet in enumerate(sheets, 1):
        page = Image.new('L', (PAGE_W, PAGE_H), 255)
        d = ImageDraw.Draw(page)
        d.text((MARGIN, MARGIN), title, fill=0, font=head)
        pg = f'{n}/{len(sheets)}'
        d.text((PAGE_W - MARGIN - d.textlength(pg, font=small), MARGIN + round(0.8 * MM)), pg, fill=90, font=small)
        d.line((MARGIN, MARGIN + HEADER - round(3 * MM), PAGE_W - MARGIN, MARGIN + HEADER - round(3 * MM)), fill=180, width=2)
        for c, column in enumerate(sheet):
            x, y = MARGIN + c * (COL_W + GAP), MARGIN + HEADER
            for i, top, bottom in column:
                img, label = images[i].crop((0, top, COL_W, bottom)), label_of(i, top)
                page.paste(img, (x, y))
                d.rectangle((x, y, x + COL_W - 1, y + img.height - 1), outline=200, width=1)   # where to cut
                d.text((x, y + img.height + round(0.8 * MM)), label, fill=40, font=small)
                y += img.height + LABEL + SPACE
        pages.append(page)
    buf = io.BytesIO()
    pages[0].save(buf, 'PDF', save_all=True, append_images=pages[1:], resolution=DPI)
    return buf.getvalue()
