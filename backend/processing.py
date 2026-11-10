"""What can be read from a file: its real type, its text (embedded or by OCR) and a preview of the first page.

Nothing here writes to the database. Problems that mean "the document is fine but needs a human" are returned in
`problems` (message keys); problems worth retrying (the OCR engine failing) raise ProcessingError."""
import io
import os
import re
import subprocess
import tempfile
import zipfile
from email import policy
from email.parser import BytesParser
from html import unescape

OCR_LANGS = os.environ.get('PATRACK_OCR_LANGS', 'ita+eng')
OCR_TIMEOUT = int(os.environ.get('PATRACK_OCR_TIMEOUT', '180'))  # seconds per page
MAX_TEXT_PAGES = 300
MAX_OCR_PAGES = 40
OCR_DPI = 300
MAX_RENDER = 5000
PREVIEW_WIDTH = 640
MIN_PAGE_TEXT = 25  # a PDF page with less embedded text than this is scanned with OCR

IMAGE_MIMES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/heic', 'image/heif', 'image/tiff', 'image/bmp'}
# Shown inline in the browser; everything else is downloaded
INLINE_MIMES = {'application/pdf', 'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'text/plain'}

EXTENSIONS = {
    '.pdf': 'application/pdf', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.gif': 'image/gif',
    '.webp': 'image/webp', '.heic': 'image/heic', '.heif': 'image/heif', '.tif': 'image/tiff', '.tiff': 'image/tiff',
    '.bmp': 'image/bmp', '.txt': 'text/plain', '.csv': 'text/csv', '.eml': 'message/rfc822', '.xml': 'application/xml',
    '.p7m': 'application/pkcs7-mime',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.doc': 'application/msword', '.xls': 'application/vnd.ms-excel', '.odt': 'application/vnd.oasis.opendocument.text',
    '.zip': 'application/zip',
}


class ProcessingError(Exception):
    """A failure worth retrying. `key` is the message shown in the import queue."""

    def __init__(self, key, detail=''):
        super().__init__(f'{key}: {detail}')
        self.key, self.detail = key, str(detail)[:500]


def sniff_mime(data: bytes, filename: str) -> str:
    """The real type from the first bytes; the extension only when the content says nothing."""
    head = data[:32]
    if head.startswith(b'%PDF') or b'%PDF-' in data[:1024]:
        return 'application/pdf'
    if head.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if head.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if head[:6] in (b'GIF87a', b'GIF89a'):
        return 'image/gif'
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'image/webp'
    if head[4:8] == b'ftyp' and head[8:12] in (b'heic', b'heix', b'hevc', b'heim', b'heis', b'mif1', b'msf1'):
        return 'image/heic'
    if head[:4] in (b'II*\x00', b'MM\x00*'):
        return 'image/tiff'
    if head[:2] == b'BM':
        return 'image/bmp'
    ext = os.path.splitext(filename or '')[1].lower()
    if head.startswith(b'PK\x03\x04'):
        return EXTENSIONS.get(ext, 'application/zip')
    return EXTENSIONS.get(ext, 'application/octet-stream')


def clean_text(s):
    s = s.replace('\x00', '').replace('\r\n', '\n').replace('\r', '\n')
    s = re.sub(r'[ \t\f\v]+', ' ', s)
    s = re.sub(r'\n\s*\n\s*\n+', '\n\n', s)
    return s.strip()


# ---------- OCR ----------

def ocr_image(img):
    """Text of a PIL image with Tesseract (Italian + English)."""
    from PIL import ImageOps
    img = ImageOps.exif_transpose(img)
    gray = img.convert('L')
    # Small photos read badly: scale them up
    if max(gray.size) < 1600:
        f = 1600 / max(gray.size)
        gray = gray.resize((int(gray.width * f), int(gray.height * f)))
    with tempfile.TemporaryDirectory(prefix='patrack-ocr-') as tmp:
        path = os.path.join(tmp, 'page.png')
        gray.save(path)
        try:
            r = subprocess.run(['tesseract', path, 'stdout', '-l', OCR_LANGS, '--psm', '3'],
                               capture_output=True, timeout=OCR_TIMEOUT)
        except FileNotFoundError:
            raise ProcessingError('ocr_unavailable', 'tesseract is not installed')
        except subprocess.TimeoutExpired:
            raise ProcessingError('ocr_timeout', f'more than {OCR_TIMEOUT}s for one page')
    if r.returncode != 0:
        raise ProcessingError('ocr_failed', r.stderr.decode(errors='replace')[-400:])
    return r.stdout.decode('utf-8', errors='replace')


def _jpeg(img, width=PREVIEW_WIDTH):
    img = img.convert('RGB')
    if img.width > width:
        img = img.resize((width, max(1, int(img.height * width / img.width))))
    out = io.BytesIO()
    img.save(out, 'JPEG', quality=78, optimize=True)
    return out.getvalue()


# ---------- By type ----------

def _pdf(data, result):
    import pypdfium2 as pdfium
    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as e:
        msg = str(e).lower()
        result['problems'].append('pdf_protected' if 'password' in msg else 'pdf_damaged')
        return
    try:
        n = len(pdf)
        result['pages'] = n
        texts, ocr_pages, embedded_pages = [], 0, 0
        for i in range(min(n, MAX_TEXT_PAGES)):
            page = pdf[i]
            try:
                tp = page.get_textpage()
                t = tp.get_text_bounded() or ''
                tp.close()
                if len(t.strip()) >= MIN_PAGE_TEXT:
                    embedded_pages += 1
                elif ocr_pages < MAX_OCR_PAGES:
                    # 300 DPI, but never more than MAX_RENDER pixels on a side (odd PDFs have huge pages)
                    scale = min(OCR_DPI / 72, MAX_RENDER / max(page.get_width(), page.get_height(), 1))
                    img = page.render(scale=scale).to_pil()
                    t = ocr_image(img)
                    ocr_pages += 1
                if i == 0:
                    result['preview'] = _jpeg(page.render(scale=PREVIEW_WIDTH / max(page.get_width(), 1)).to_pil())
            finally:
                page.close()
            texts.append(t)
        if n > MAX_TEXT_PAGES or (ocr_pages >= MAX_OCR_PAGES and n - embedded_pages > MAX_OCR_PAGES):
            result['problems'].append('partially_read')
        result['text'] = '\n\n'.join(texts)
        result['text_source'] = 'mixed' if ocr_pages and embedded_pages else 'ocr' if ocr_pages else 'pdf'
    finally:
        pdf.close()


def _image(data, result):
    from PIL import Image
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        result['problems'].append('image_unreadable')
        return
    from PIL import ImageOps
    img = ImageOps.exif_transpose(img)
    result['pages'] = 1
    result['preview'] = _jpeg(img)
    result['text'] = ocr_image(img)
    result['text_source'] = 'ocr'


def _html_to_text(html):
    html = re.sub(r'(?is)<(script|style|head).*?</\1>', ' ', html)
    html = re.sub(r'(?i)<br\s*/?>|</p>|</div>|</tr>|</li>|</h\d>', '\n', html)
    return unescape(re.sub(r'<[^>]+>', ' ', html))


def email_text(msg):
    """Readable text of an email: headers that matter and the body (plain text preferred)."""
    head = '\n'.join(f'{h}: {msg[h]}' for h in ('From', 'To', 'Date', 'Subject') if msg[h])
    part = msg.get_body(preferencelist=('plain', 'html'))
    body = ''
    if part is not None:
        try:
            body = part.get_content()
        except Exception:
            body = (part.get_payload(decode=True) or b'').decode('utf-8', errors='replace')
        if part.get_content_type() == 'text/html':
            body = _html_to_text(body)
    return head + '\n\n' + body


def _eml(data, result):
    msg = BytesParser(policy=policy.default).parsebytes(data)
    result['text'] = email_text(msg)
    result['text_source'] = 'email'
    result['pages'] = 1


def _docx(data, result):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read('word/document.xml').decode('utf-8', errors='replace')
    except Exception:
        result['problems'].append('unsupported_format')
        return
    xml = re.sub(r'</w:p>', '\n', xml)
    result['text'] = unescape(re.sub(r'<[^>]+>', '', xml))
    result['text_source'] = 'text'


def _plain(data, result):
    for enc in ('utf-8', 'cp1252', 'latin-1'):
        try:
            result['text'] = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    result['text_source'] = 'text'
    result['pages'] = 1


def process(data: bytes, mime: str) -> dict:
    """{text, text_source, pages, preview (JPEG bytes or None), problems: [message keys]}."""
    result = {'text': '', 'text_source': None, 'pages': None, 'preview': None, 'problems': []}
    if mime == 'application/pdf':
        _pdf(data, result)
    elif mime in IMAGE_MIMES:
        _image(data, result)
    elif mime == 'message/rfc822':
        _eml(data, result)
    elif mime.endswith('wordprocessingml.document'):
        _docx(data, result)
    elif mime.startswith('text/') or mime == 'application/xml':
        _plain(data, result)
    else:
        result['problems'].append('unsupported_format')
    result['text'] = clean_text(result['text'])[:1_000_000]
    if not result['problems'] and len(re.sub(r'\W', '', result['text'])) < 10:
        result['problems'].append('no_text')
    return result
