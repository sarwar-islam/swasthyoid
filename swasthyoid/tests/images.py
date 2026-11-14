"""Valid synthetic images for the upload tests (decision D5: an upload is now really decoded and quality-checked).

Every image is a rendering of a synthetic placeholder prescription (tests/evaluation/generate.py): no real text. PNG and
JPEG are clean pages that pass the provisional quality checks; the others are made on demand for one purpose each (EXIF,
a poor page, a damaged file). Nothing here is written to disk.
"""
import io

from PIL import Image

from swasthyoid.tests import synthetic
from swasthyoid.tests.evaluation import generate


def page(seed=11):
    """A clean synthetic page as a Pillow image (grey, 1000 x 1400) and its PNG bytes."""
    prescription = synthetic.make_prescriptions(synthetic.make_patients(1, seed), seed, per_patient=1)[0]
    image, _ = generate.render(prescription)
    return image


def encode(image, fmt="PNG", **options):
    out = io.BytesIO()
    image.save(out, format=fmt, **options)
    return out.getvalue()


PNG = encode(page(11))
JPEG = encode(page(12), "JPEG", quality=92)  # a different page from PNG, so their hashes differ


def jpeg_with_metadata(orientation=1, size=None):
    """A JPEG that carries EXIF (orientation, make, a GPS latitude reference and a timestamp) and a comment. With
    orientation 6 the pixels are stored rotated so that the picture, once the orientation is applied, is the clean page."""
    image = page(13)
    if orientation == 6:
        image = image.rotate(90, expand=True)  # stored sideways; "6" says: rotate 90 degrees clockwise to display it
    exif = Image.Exif()
    exif[0x0112] = orientation
    exif[0x010F] = "SYNTHETIC-CAMERA-MAKER"
    exif[0x0132] = "2026:01:02 03:04:05"
    exif.get_ifd(0x8825)[1] = "N"  # GPSLatitudeRef: a GPS block exists
    return encode(image, "JPEG", quality=92, exif=exif.tobytes(), comment=b"SYNTHETIC-COMMENT")


def png_with_metadata():
    from PIL import PngImagePlugin
    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", "SYNTHETIC-PNG-COMMENT")
    return encode(page(14), "PNG", pnginfo=info)


def poor_page(kind):
    """The clean page with one degradation, as PNG bytes. kind: blur, glare, low_contrast, rotate, small."""
    image = page(15)
    if kind == "small":
        return encode(image.resize((400, 560)))
    amount = {"blur": 5, "glare": 0.5, "low_contrast": 0.15, "rotate": 8}[kind]
    return encode(generate.degrade(image, kind, amount, 0))


def truncated(data=None):
    data = data or PNG
    return data[: len(data) // 3]


def mpo():
    """A multi-picture JPEG (what Pillow calls MPO): two frames, the first is the clean page."""
    out = io.BytesIO()
    first, second = page(16), page(17)
    first.convert("RGB").save(out, format="MPO", save_all=True, append_images=[second.convert("RGB")])
    return out.getvalue()
