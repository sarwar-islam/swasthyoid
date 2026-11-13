"""Image validation and quality measurement (M2 step 5A; docs/M2_COMPLETION_PLAN.md).

Model-independent and pure: bytes in, a decision or numbers out. Nothing here writes, stores or
changes an image, so an original is never touched. NOT yet called by the upload path: refusing
uploads depends on the retake policy (D5) and on limits calibrated on the labelled degraded set
(step 3A, measured by tests/evaluation); until then these are measurements.

LIMITS are PROVISIONAL engineering values, not clinical ones and not approved (pass marks are
D11). Measured limits on the synthetic degraded set (seed 1): Laplacian variance rises with noise,
so noise is not reported as blur and heavy noise (sigma 30) is wrongly reported as glare; mild
low contrast (0.3) is caught on only half of the pages; rotation is not detected at all. Reason codes follow the plan: image_blurry, image_glare, image_too_small, plus
image_undecodable, image_unsupported and image_too_large for files that cannot be used at all.
"""
import io

import numpy as np
from PIL import Image, UnidentifiedImageError

FORMATS = {"JPEG", "PNG"}
MAX_PIXELS = 40_000_000  # decompression-bomb cap, checked from the header before any pixel is decoded
LIMITS = {"min_side": 600, "min_sharpness": 60.0, "max_glare": 0.02}  # PROVISIONAL, see above
GLARE_LEVEL = 250  # grey level counted as blown out


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


def measure(data):
    """{width, height, sharpness, glare}: sharpness is the variance of the Laplacian (higher is
    sharper), glare the share of pixels at or above GLARE_LEVEL. Raises ImageRejected."""
    grey = decode(data).astype(np.float64)
    height, width = grey.shape
    if height < 3 or width < 3:
        return {"width": width, "height": height, "sharpness": 0.0, "glare": float((grey >= GLARE_LEVEL).mean())}
    laplacian = (grey[:-2, 1:-1] + grey[2:, 1:-1] + grey[1:-1, :-2] + grey[1:-1, 2:] - 4 * grey[1:-1, 1:-1])
    return {"width": width, "height": height, "sharpness": float(laplacian.var()),
            "glare": float((grey >= GLARE_LEVEL).mean())}


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
    return reasons
