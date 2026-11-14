"""User-facing retake guidance for the image-quality reason codes (M2 step 5A, decision D5, docs/DECISIONS.md "Phase 5").

The machine-readable reason codes live in capture/imaging.py and are never changed here. This module only maps a code to
text for a person, in one place, keyed by language so that English (or another language) is one more key and no endpoint
holds a string of its own. The text says how to take a better photo. It states nothing about the document's content or any
clinical meaning. The Bangla wording was approved by the owner as written (2026-11-14); a native-speaker review is pending.
"""
GUIDANCE = {
    "image_blurry": {"bn": "ছবিটি ঝাপসা হয়েছে। ক্যামেরা স্থির রেখে আবার পরিষ্কার ছবি তুলুন।"},
    "image_glare": {"bn": "ছবিতে অতিরিক্ত আলো বা প্রতিফলন রয়েছে। আলো পরিবর্তন করে আবার ছবি তুলুন।"},
    "image_low_contrast": {"bn": "লেখাগুলো স্পষ্ট দেখা যাচ্ছে না। পর্যাপ্ত আলোতে আবার ছবি তুলুন।"},
    "image_skewed": {"bn": "কাগজটি বাঁকা অবস্থায় তোলা হয়েছে। ক্যামেরা কাগজের সমান্তরালে রেখে ছবি তুলুন।"},
    "image_too_small": {"bn": "ছবির রেজোলিউশন কম। কাগজের আরও কাছে গিয়ে পরিষ্কার ছবি তুলুন।"},
}
QUALITY_CODES = tuple(GUIDANCE)


def guidance_for(reasons):
    """[{"code": reason, <language>: text, ...}] for each reason code, in the order given. An unknown code is kept with no
    text (the client can still show the code) rather than dropped."""
    return [{"code": code, **GUIDANCE.get(code, {})} for code in reasons]
