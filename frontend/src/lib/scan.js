// Document scanner, all in the browser: find the sheet in a photo, straighten it, clean it up, make a PDF.
// No libraries: the sheet is found as the largest bright area (paper on a darker surface), its corners are the
// extreme points of that area; the user can drag them before confirming.

/** Load an image file into a canvas, at most `max` pixels on the long side (EXIF orientation applied by the browser). */
export async function loadImage(file, max = 3000) {
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise((resolve, reject) => {
      const i = new Image();
      i.onload = () => resolve(i);
      i.onerror = () => reject(new Error('image'));
      i.src = url;
    });
    const f = Math.min(1, max / Math.max(img.naturalWidth, img.naturalHeight));
    const c = document.createElement('canvas');
    c.width = Math.round(img.naturalWidth * f);
    c.height = Math.round(img.naturalHeight * f);
    c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
    return c;
  } finally {
    URL.revokeObjectURL(url);
  }
}

function otsu(hist, total) {
  let sum = 0;
  for (let i = 0; i < 256; i++) sum += i * hist[i];
  let sumB = 0, wB = 0, best = 0, threshold = 128;
  for (let i = 0; i < 256; i++) {
    wB += hist[i];
    if (!wB) continue;
    const wF = total - wB;
    if (!wF) break;
    sumB += i * hist[i];
    const mB = sumB / wB, mF = (sum - sumB) / wF;
    const between = wB * wF * (mB - mF) ** 2;
    if (between > best) { best = between; threshold = i; }
  }
  return threshold;
}

/** Corners [tl, tr, br, bl] ({x, y} in canvas pixels) of the sheet in the photo; a slightly inset frame if none is found. */
export function detectCorners(canvas) {
  const W = 360;
  const f = Math.min(1, W / Math.max(canvas.width, canvas.height));
  const w = Math.max(1, Math.round(canvas.width * f)), h = Math.max(1, Math.round(canvas.height * f));
  const small = document.createElement('canvas');
  small.width = w; small.height = h;
  const ctx = small.getContext('2d', { willReadFrequently: true });
  ctx.filter = 'blur(2px)';
  ctx.drawImage(canvas, 0, 0, w, h);
  const px = ctx.getImageData(0, 0, w, h).data;
  const gray = new Uint8Array(w * h);
  const hist = new Uint32Array(256);
  for (let i = 0, j = 0; i < gray.length; i++, j += 4) {
    const v = (px[j] * 0.299 + px[j + 1] * 0.587 + px[j + 2] * 0.114) | 0;
    gray[i] = v; hist[v]++;
  }
  const thr = otsu(hist, gray.length);
  // Largest bright connected area
  const label = new Int32Array(w * h).fill(-1);
  let bestSize = 0, bestLabel = -1, current = 0;
  const stack = new Int32Array(w * h);
  for (let start = 0; start < gray.length; start++) {
    if (gray[start] <= thr || label[start] !== -1) continue;
    let top = 0, size = 0;
    stack[top++] = start; label[start] = current;
    while (top) {
      const p = stack[--top]; size++;
      const x = p % w, y = (p / w) | 0;
      if (x > 0 && label[p - 1] === -1 && gray[p - 1] > thr) { label[p - 1] = current; stack[top++] = p - 1; }
      if (x < w - 1 && label[p + 1] === -1 && gray[p + 1] > thr) { label[p + 1] = current; stack[top++] = p + 1; }
      if (y > 0 && label[p - w] === -1 && gray[p - w] > thr) { label[p - w] = current; stack[top++] = p - w; }
      if (y < h - 1 && label[p + w] === -1 && gray[p + w] > thr) { label[p + w] = current; stack[top++] = p + w; }
    }
    if (size > bestSize) { bestSize = size; bestLabel = current; }
    current++;
  }
  const area = bestSize / (w * h);
  if (bestLabel < 0 || area < 0.12 || area > 0.97) return insetFrame(canvas);
  let tl = null, tr = null, br = null, bl = null;
  let minSum = Infinity, maxSum = -Infinity, minDiff = Infinity, maxDiff = -Infinity;
  for (let p = 0; p < label.length; p++) {
    if (label[p] !== bestLabel) continue;
    const x = p % w, y = (p / w) | 0;
    const s = x + y, d = x - y;
    if (s < minSum) { minSum = s; tl = { x, y }; }
    if (s > maxSum) { maxSum = s; br = { x, y }; }
    if (d > maxDiff) { maxDiff = d; tr = { x, y }; }
    if (d < minDiff) { minDiff = d; bl = { x, y }; }
  }
  const quad = [tl, tr, br, bl].map((q) => ({ x: (q.x + 0.5) / f, y: (q.y + 0.5) / f }));
  // A degenerate shape (e.g. a triangle) is worse than the whole photo
  if (polygonArea(quad) < 0.1 * canvas.width * canvas.height) return insetFrame(canvas);
  return quad;
}

export function insetFrame(canvas, m = 0.04) {
  const w = canvas.width, h = canvas.height;
  return [{ x: w * m, y: h * m }, { x: w * (1 - m), y: h * m }, { x: w * (1 - m), y: h * (1 - m) }, { x: w * m, y: h * (1 - m) }];
}
export function fullFrame(canvas) { return insetFrame(canvas, 0); }

function polygonArea(q) {
  let a = 0;
  for (let i = 0; i < q.length; i++) {
    const p = q[i], n = q[(i + 1) % q.length];
    a += p.x * n.y - n.x * p.y;
  }
  return Math.abs(a / 2);
}

const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);

/** Solve A·x = b (8×8) with Gaussian elimination. */
function solve(A, b) {
  const n = b.length;
  for (let i = 0; i < n; i++) {
    let max = i;
    for (let r = i + 1; r < n; r++) if (Math.abs(A[r][i]) > Math.abs(A[max][i])) max = r;
    [A[i], A[max]] = [A[max], A[i]]; [b[i], b[max]] = [b[max], b[i]];
    for (let r = i + 1; r < n; r++) {
      const k = A[r][i] / A[i][i];
      for (let c = i; c < n; c++) A[r][c] -= k * A[i][c];
      b[r] -= k * b[i];
    }
  }
  const x = new Array(n);
  for (let i = n - 1; i >= 0; i--) {
    let s = b[i];
    for (let c = i + 1; c < n; c++) s -= A[i][c] * x[c];
    x[i] = s / A[i][i];
  }
  return x;
}

/** Homography mapping the 4 points `from` onto `to`. */
function homography(from, to) {
  const A = [], b = [];
  for (let i = 0; i < 4; i++) {
    const { x, y } = from[i], { x: u, y: v } = to[i];
    A.push([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.push(u);
    A.push([0, 0, 0, x, y, 1, -v * x, -v * y]); b.push(v);
  }
  return [...solve(A, b), 1];
}

/** Straighten the quad [tl, tr, br, bl] of `src` into a new canvas (long side at most `max`). */
export function warp(src, quad, max = 2200) {
  let W = Math.max(dist(quad[0], quad[1]), dist(quad[3], quad[2]));
  let H = Math.max(dist(quad[0], quad[3]), dist(quad[1], quad[2]));
  const f = Math.min(1, max / Math.max(W, H));
  W = Math.max(1, Math.round(W * f)); H = Math.max(1, Math.round(H * f));
  const m = homography([{ x: 0, y: 0 }, { x: W - 1, y: 0 }, { x: W - 1, y: H - 1 }, { x: 0, y: H - 1 }], quad);
  const sctx = src.getContext('2d', { willReadFrequently: true });
  const sw = src.width, sh = src.height;
  const s = sctx.getImageData(0, 0, sw, sh).data;
  const out = document.createElement('canvas');
  out.width = W; out.height = H;
  const octx = out.getContext('2d');
  const img = octx.createImageData(W, H);
  const d = img.data;
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const z = m[6] * x + m[7] * y + m[8];
      let sx = (m[0] * x + m[1] * y + m[2]) / z, sy = (m[3] * x + m[4] * y + m[5]) / z;
      sx = Math.min(Math.max(sx, 0), sw - 1.001); sy = Math.min(Math.max(sy, 0), sh - 1.001);
      const x0 = sx | 0, y0 = sy | 0, fx = sx - x0, fy = sy - y0;
      const i00 = (y0 * sw + x0) * 4, i10 = i00 + 4, i01 = i00 + sw * 4, i11 = i01 + 4;
      const o = (y * W + x) * 4;
      for (let c = 0; c < 3; c++) {
        d[o + c] = (s[i00 + c] * (1 - fx) + s[i10 + c] * fx) * (1 - fy) + (s[i01 + c] * (1 - fx) + s[i11 + c] * fx) * fy;
      }
      d[o + 3] = 255;
    }
  }
  octx.putImageData(img, 0, 0);
  return out;
}

/** "Documento": grey levels stretched so the paper becomes white and the ink dark. Changes the canvas in place. */
export function enhance(canvas) {
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const d = img.data;
  const hist = new Uint32Array(256);
  const n = d.length / 4;
  for (let i = 0; i < d.length; i += 4) hist[(d[i] * 0.299 + d[i + 1] * 0.587 + d[i + 2] * 0.114) | 0]++;
  const pct = (p) => { let acc = 0; for (let i = 0; i < 256; i++) { acc += hist[i]; if (acc >= n * p) return i; } return 255; };
  const lo = pct(0.02), hi = Math.max(lo + 30, pct(0.6));
  for (let i = 0; i < d.length; i += 4) {
    const g = d[i] * 0.299 + d[i + 1] * 0.587 + d[i + 2] * 0.114;
    let v = ((g - lo) / (hi - lo)) * 255;
    v = v < 0 ? 0 : v > 255 ? 255 : v;
    d[i] = d[i + 1] = d[i + 2] = v;
  }
  ctx.putImageData(img, 0, 0);
  return canvas;
}

export function canvasToJpeg(canvas, quality = 0.82) {
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', quality));
}

/** A PDF with one JPEG per page (A4 width, height from the image proportions). */
export async function makePdf(pages) {
  const enc = new TextEncoder();
  const parts = [];
  let length = 0;
  const offsets = [];
  const push = (chunk) => { const b = typeof chunk === 'string' ? enc.encode(chunk) : chunk; parts.push(b); length += b.length; };
  const obj = (id, body, stream) => {
    offsets[id] = length;
    push(`${id} 0 obj\n${body}\n`);
    if (stream) { push('stream\n'); push(stream); push('\nendstream\n'); }
    push('endobj\n');
  };
  push('%PDF-1.4\n%\xE2\xE3\xCF\xD3\n');
  const n = pages.length;
  const pageIds = pages.map((_, i) => 3 + i * 3);
  obj(1, '<< /Type /Catalog /Pages 2 0 R >>');
  obj(2, `<< /Type /Pages /Kids [${pageIds.map((id) => `${id} 0 R`).join(' ')}] /Count ${n} >>`);
  for (let i = 0; i < n; i++) {
    const { blob, width, height } = pages[i];
    const jpeg = new Uint8Array(await blob.arrayBuffer());
    const pw = 595.28, ph = +(pw * height / width).toFixed(2);
    const [pageId, contentId, imageId] = [pageIds[i], pageIds[i] + 1, pageIds[i] + 2];
    const content = enc.encode(`q ${pw} 0 0 ${ph} 0 0 cm /Im0 Do Q`);
    obj(pageId, `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pw} ${ph}] /Resources << /XObject << /Im0 ${imageId} 0 R >> >> /Contents ${contentId} 0 R >>`);
    obj(contentId, `<< /Length ${content.length} >>`, content);
    obj(imageId, `<< /Type /XObject /Subtype /Image /Width ${width} /Height ${height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpeg.length} >>`, jpeg);
  }
  const size = 3 + n * 3;
  const xref = length;
  let table = `xref\n0 ${size}\n0000000000 65535 f \n`;
  for (let i = 1; i < size; i++) table += `${String(offsets[i]).padStart(10, '0')} 00000 n \n`;
  push(table + `trailer\n<< /Size ${size} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`);
  return new Blob(parts, { type: 'application/pdf' });
}
