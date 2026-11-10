"""Files made on the fly for the tests: PDFs with text, scanned-like PDFs, photos of text, emails."""
import io
from email.message import EmailMessage


def pdf_with_text(lines, pages=1):
    """A real PDF with embedded text (Helvetica), one or more pages."""
    objs = []
    kids = []
    font_id = 3
    page_ids = []
    next_id = 4
    contents = []
    for p in range(pages):
        stream = 'BT /F1 14 Tf 50 780 Td 18 TL ' + ' '.join(f'({line} p{p + 1}) Tj T*' if pages > 1 else f'({line}) Tj T*'
                                                           for line in lines) + ' ET'
        page_id, content_id = next_id, next_id + 1
        next_id += 2
        page_ids.append(page_id)
        contents.append((page_id, content_id, stream))
    objs.append((1, '<< /Type /Catalog /Pages 2 0 R >>'))
    objs.append((2, f"<< /Type /Pages /Kids [{' '.join(f'{i} 0 R' for i in page_ids)}] /Count {len(page_ids)} >>"))
    objs.append((font_id, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>'))
    for page_id, content_id, stream in contents:
        objs.append((page_id, f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 {font_id} 0 R >> >> '
                              f'/Contents {content_id} 0 R >>'))
        data = stream.encode('latin-1')
        objs.append((content_id, f'<< /Length {len(data)} >>\nstream\n{stream}\nendstream'))
    del kids
    out = io.BytesIO()
    out.write(b'%PDF-1.4\n')
    offsets = {}
    for oid, body in sorted(objs):
        offsets[oid] = out.tell()
        out.write(f'{oid} 0 obj\n{body}\nendobj\n'.encode('latin-1'))
    xref = out.tell()
    n = max(offsets) + 1
    out.write(f'xref\n0 {n}\n0000000000 65535 f \n'.encode())
    for i in range(1, n):
        out.write(f'{offsets[i]:010d} 00000 n \n'.encode())
    out.write(f'trailer\n<< /Size {n} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    return out.getvalue()


def text_image(lines, fmt='PNG', size=(1400, 900)):
    """A white image with big black text, like a photo of a page."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new('RGB', size, 'white')
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=48)
    y = 60
    for line in lines:
        d.text((60, y), line, fill='black', font=font)
        y += 80
    out = io.BytesIO()
    img.save(out, fmt)
    return out.getvalue()


def scanned_pdf(lines):
    """A PDF that contains only an image of text (no embedded text): needs OCR."""
    from PIL import Image
    img = Image.open(io.BytesIO(text_image(lines)))
    out = io.BytesIO()
    img.save(out, 'PDF', resolution=150)
    return out.getvalue()


def email_with(attachments=(), sender='fil@example.com', subject='Bolletta', body='Ciao', auth='spf=pass smtp.mailfrom=x',
               message_id='<m1@example.com>', inline_logo=False):
    msg = EmailMessage()
    msg['From'] = f'Fil <{sender}>'
    msg['To'] = 'archivio@example.com'
    msg['Subject'] = subject
    msg['Message-ID'] = message_id
    if auth is not None:
        msg['Authentication-Results'] = f'mx.example.com; {auth}'
    msg.set_content(body)
    if inline_logo:
        msg.add_alternative('<p>Ciao <img src="cid:logo"></p>', subtype='html')
        msg.get_payload()[1].add_related(b'\x89PNG\r\n\x1a\n' + b'0' * 500, 'image', 'png', cid='<logo>', filename='image001.png',
                                         disposition='inline')
    for name, data, ctype in attachments:
        maintype, subtype = ctype.split('/')
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return msg.as_bytes()
