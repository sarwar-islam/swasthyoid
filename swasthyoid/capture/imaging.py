"""Image validation, quality measurement and processing copies (M2 step 5; docs/M2_COMPLETION_PLAN.md).

Model-independent and pure: bytes in, a decision, numbers or NEW bytes out. Nothing here writes,
stores or changes an input, so an original is never touched. NOT called by the upload path:
refusing uploads depends on the retake policy (D5) and on limits calibrated on the labelled
degraded set (tests/evaluation); until those are decided these are measurements.

LIMITS are PROVISIONAL engineering values, not clinical ones and not approved (pass marks are
D11). Reason codes: image_blurry, image_glare, image_too_small, image_low_contrast, image_skewed
for a page that should be retaken; image_undecodable, image_unsupported, image_too_large for a
file that cannot be used at all.

Measured on the synthetic degraded set (tests/evaluation, seed 1):
- sharpness is the variance of the Laplacian of a 3x3 box-filtered page, so per-pixel noise no
  longer reads as sharpness the way it did unfiltered; noise still raises the score a little, so a
  page that is both blurred and noisy could pass;
- glare is the share of 16x16 blocks whose median is blown out, so scattered noise no longer reads
  as glare;
- contrast is the paper level minus the 1st percentile (ink depth);
- skew is estimated from a projection profile and is exact on the synthetic pages (3 and 8
  degrees); it needs text lines, so a page without text reports 0.
Real photographs may behave differently: nothing here is calibrated on them.

process() makes the processing copy (plan step 5B). Every operation is a separate switch and all
are off by default, because a model trained on unprocessed photos may do worse with them.
"""
import io

import numpy as np
from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError

FORMATS = {"JPEG", "PNG"}
MAX_PIXELS = 40_000_000  # decompression-bomb cap, checked from the header before any pixel is decoded
LIMITS = {"min_side": 600, "min_sharpness": 20.0, "max_glare": 0.02, "min_contrast": 75.0,
          "max_skew": 2.0}  # PROVISIONAL, see above
GLARE_LEVEL = 250  # grey level counted as blown out
BLOCK = 16
SKEW_RANGE, SKEW_STEP, SKEW_WIDTH = 12.0, 0.5, 300  # search +-12 degrees on a 300-pixel-wide copy


class ImageRejected(Exception):
    """The file cannot be used; args[0] is a reason code, never file content."""


def decode(data):
    """The image as an 8-bit grey NumPy array. Raises ImageRejected for anything that is not a
    decodable JPEG or PNG within the pixel cap. Does not trust the first bytes: it decodes."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in FORMATS:
                raise ImageRejected("image_unsupported")
            width, height = image.size
            if width * height > MAX_PIXELS:
                raise ImageRejected("image_too_large")  # before decoding: a small file can expand enormously
            image.load()
            return np.asarray(image.convert("L"))
    except ImageRejected:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise ImageRejected("image_undecodable") from None


def _sharpness(grey):
    height, width = grey.shape
    box = sum(grey[i:height - 2 + i, j:width - 2 + j] for i in range(3) for j in range(3)) / 9
    return float((box[:-2, 1:-1] + box[2:, 1:-1] + box[1:-1, :-2] + box[1:-1, 2:] - 4 * box[1:-1, 1:-1]).var())


def _glare(grey):
    rows, cols = grey.shape[0] // BLOCK, grey.shape[1] // BLOCK
    if not rows or not cols:
        return float((grey >= GLARE_LEVEL).mean())
    blocks = grey[:rows * BLOCK, :cols * BLOCK].reshape(rows, BLOCK, cols, BLOCK).swapaxes(1, 2).reshape(-1, BLOCK * BLOCK)
    return float((np.median(blocks, axis=1) >= GLARE_LEVEL).mean())


def _skew(grey):
    """Degrees the page is rotated counter-clockwise (the page needs rotating clockwise by this
    much); 0.0 when there is no text to measure."""
    small = Image.fromarray(grey).resize((SKEW_WIDTH, max(1, round(SKEW_WIDTH * grey.shape[0] / grey.shape[1]))))
    pixels = np.asarray(small)
    ink = ((pixels < np.median(pixels) - 40) * 255).astype(np.uint8)
    if not ink.any():
        return 0.0
    best, best_variance = 0.0, -1.0
    for angle in np.arange(-SKEW_RANGE, SKEW_RANGE + 1e-9, SKEW_STEP):
        variance = float(np.asarray(Image.fromarray(ink).rotate(angle, resample=Image.BILINEAR))
                         .sum(axis=1).astype(np.float64).var())
        if variance > best_variance + 1e-9:  # on a tie the first (most negative) angle is kept
            best, best_variance = float(angle), variance
    return -best


def measure(data):
    """{width, height, sharpness, glare, contrast, skew}. Raises ImageRejected."""
    grey = decode(data)
    height, width = grey.shape
    flat = grey.astype(np.float32)
    contrast = float(np.median(flat) - np.percentile(flat, 1))
    if height < 5 or width < 5:
        return {"width": width, "height": height, "sharpness": 0.0, "glare": _glare(grey),
                "contrast": contrast, "skew": 0.0}
    return {"width": width, "height": height, "sharpness": _sharpness(flat), "glare": _glare(grey),
            "contrast": contrast, "skew": _skew(grey)}


def check(data, limits=None):
    """Reason codes for a page that should be retaken (empty list: acceptable). A file that cannot
    be used at all raises ImageRejected. Refusing is the caller's policy (D5), not this function's."""
    limits = {**LIMITS, **(limits or {})}
    m = measure(data)
    reasons = []
    if min(m["width"], m["height"]) < limits["min_side"]:
        reasons.append("image_too_small")
    if m["sharpness"] < limits["min_sharpness"]:
        reasons.append("image_blurry")
    if m["glare"] > limits["max_glare"]:
        reasons.append("image_glare")
    if m["contrast"] < limits["min_contrast"]:
        reasons.append("image_low_contrast")
    if abs(m["skew"]) > limits["max_skew"]:
        reasons.append("image_skewed")
    return reasons


def process(data, *, exif=False, deskew=False, denoise=False, contrast=False):
    """A processing copy as PNG bytes and the list of operations applied, in order. The input is
    only read. exif applies the EXIF orientation, deskew rotates by the measured skew, denoise is a
    3x3 median filter, contrast stretches the grey range (1% clipped at each end). With every
    switch off the copy is the grey image. Raises ImageRejected like decode()."""
    decode(data)  # the same refusals as everywhere else, before any work
    applied = []
    with Image.open(io.BytesIO(data)) as source:
        image = ImageOps.exif_transpose(source) if exif else source.copy()
        if exif:
            applied.append("exif")
        image = image.convert("L")
    if deskew:
        grey = np.asarray(image)
        angle = _skew(grey)
        if angle:
            image = image.rotate(-angle, resample=Image.BILINEAR, fillcolor=int(np.median(grey)))
        applied.append("deskew")
    if denoise:
        image = image.filter(ImageFilter.MedianFilter(3))
        applied.append("denoise")
    if contrast:
        image = ImageOps.autocontrast(image, cutoff=1)
        applied.append("contrast")
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue(), applied
