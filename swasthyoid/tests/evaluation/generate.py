"""Synthetic printed documents with exact ground truth, and degraded copies (step 3A-data).

Everything is derived from tests/synthetic.py placeholders: no real names, no clinical content,
no drug names, doses or reference values. English labels only until a font with a licence that
allows Bangla rendering is chosen (plan, step 3A; not decided here). The same seed in the same
environment yields identical ground truth and identical PNG bytes. Large sets are generated on
demand, never committed.
"""
import hashlib
import io
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from swasthyoid.tests import synthetic

VERSION = "1"  # bump when the layout or the degradations change: it is part of the dataset identity
SIZE = (1000, 1400)
PAPER = 225  # photographed paper rarely reaches pure white; glare is what reaches 255
HELD_OUT_SHARE = 0.25
DEGRADATIONS = ("rotate", "blur", "noise", "glare", "low_contrast")


def _png(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def render(prescription):
    """One clean printed page for a prescription, plus its ground truth."""
    image = Image.new("L", SIZE, PAPER)
    draw, font = ImageDraw.Draw(image), ImageFont.load_default(size=34)
    y = 80
    draw.text((60, y), f"SYNTHETIC PRESCRIPTION {prescription['prescription_id']}", fill=20, font=font)
    y += 90
    for item in prescription["items"]:
        for text in (f"Drug: {item['drug']}", f"Dose: {item['dose']}", f"Frequency: {item['frequency']}"):
            draw.text((90, y), text, fill=20, font=font)
            y += 60
        y += 40
    truth = {"document_id": prescription["prescription_id"], "doc_type": "prescription", "version": VERSION,
             "items": [dict(item) for item in prescription["items"]], "synthetic": True}
    return image, truth


def degrade(image, kind, amount, seed):
    """A degraded copy: rotate (degrees), blur (radius), noise (sigma), glare (share of the page
    width of a saturated blob), low_contrast (factor kept, 0 to 1). Deterministic for a seed."""
    if kind == "rotate":
        return image.rotate(amount, expand=False, fillcolor=PAPER)
    if kind == "blur":
        return image.filter(ImageFilter.GaussianBlur(amount))
    if kind == "noise":
        noise = np.random.default_rng(seed).normal(0, amount, (image.height, image.width))
        return Image.fromarray(np.clip(np.asarray(image) + noise, 0, 255).astype(np.uint8))
    if kind == "glare":
        copy, radius = image.copy(), int(image.width * amount / 2)
        ImageDraw.Draw(copy).ellipse((image.width // 2 - radius, image.height // 3 - radius,
                                      image.width // 2 + radius, image.height // 3 + radius), fill=255)
        return copy
    if kind == "low_contrast":
        return Image.fromarray((PAPER + (np.asarray(image, dtype=np.float64) - PAPER) * amount).astype(np.uint8))
    raise ValueError(kind)


AMOUNTS = {"rotate": (3, 8), "blur": (2, 5), "noise": (10, 30), "glare": (0.3, 0.5), "low_contrast": (0.3, 0.15)}


def build(seed=0, patients=8):
    """The dataset: documents with ground truth and a split, and degraded copies that record
    their degradation type and amount."""
    people = synthetic.make_patients(patients, seed)
    prescriptions = synthetic.make_prescriptions(people, seed, per_patient=1)
    ids = sorted(p["prescription_id"] for p in prescriptions)
    random.Random(seed).shuffle(ids)
    held_out = set(ids[:max(1, int(len(ids) * HELD_OUT_SHARE))])
    documents, copies = [], []
    for number, prescription in enumerate(prescriptions):
        image, truth = render(prescription)
        data = _png(image)
        doc_id = prescription["prescription_id"]
        documents.append({"id": doc_id, "split": "held_out" if doc_id in held_out else "development",
                          "truth": truth, "png": data, "sha256": sha256(data)})
        for kind in DEGRADATIONS:
            for amount in AMOUNTS[kind]:
                copy = _png(degrade(image, kind, amount, seed * 100_000 + number))
                copies.append({"document_id": doc_id, "degradation": kind, "amount": amount,
                               "png": copy, "sha256": sha256(copy)})
    return {"version": VERSION, "seed": seed, "documents": documents, "copies": copies}
