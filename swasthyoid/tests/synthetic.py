"""Synthetic data generator stub (FRD invariant 9). Fake patients and prescriptions only.

Nothing here is clinical: drug names, doses and frequencies are opaque placeholders.
CLINICAL-REVIEWER-PLACEHOLDER: realistic drugs/doses need the catalog decision
(docs/DECISIONS.md, question 1) and reviewer sign-off (question 7).
"""
import random


def make_patients(n, seed=0):
    rng = random.Random(seed)
    return [
        {
            "patient_id": f"SYNTH-PATIENT-{i:04d}",
            "name": f"Synthetic Patient {i}",
            "birth_year": rng.randint(1940, 2010),
            "synthetic": True,
        }
        for i in range(1, n + 1)
    ]


def make_prescriptions(patients, seed=0, per_patient=2):
    rng = random.Random(seed)
    return [
        {
            "prescription_id": f"SYNTH-RX-{p['patient_id'][-4:]}-{j}",
            "patient_id": p["patient_id"],
            "items": [
                {
                    "drug": f"SYNTH-DRUG-{rng.randint(1, 20):03d}",
                    "dose": "PLACEHOLDER-DOSE",
                    "frequency": "PLACEHOLDER-FREQUENCY",
                }
                for _ in range(rng.randint(1, 3))
            ],
            "synthetic": True,
        }
        for p in patients
        for j in range(1, per_patient + 1)
    ]


if __name__ == "__main__":
    import json

    patients = make_patients(3)
    print(json.dumps({"patients": patients, "prescriptions": make_prescriptions(patients)}, indent=2))
