from swasthyoid.tests.synthetic import make_patients, make_prescriptions


def test_seeded_and_flagged_synthetic():
    patients = make_patients(5, seed=1)
    rxs = make_prescriptions(patients, seed=1)
    assert patients == make_patients(5, seed=1)
    assert rxs == make_prescriptions(patients, seed=1)
    assert len(rxs) == 10
    assert all(r["synthetic"] for r in patients + rxs)
    assert {r["patient_id"] for r in rxs} == {p["patient_id"] for p in patients}
