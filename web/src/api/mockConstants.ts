// The few synthetic values screens show in mock mode (sign-in hints, demo codes). Kept apart from mock.ts so a live build
// does not carry the whole mock (UX-3a); mock.ts re-exports them.
export const MOCK_CODE = "123456"; // the one-time code the mock accepts (no SMS in the mock)
export const MOCK_PHONE = "+8801700000001"; // already registered; any other phone must register with a profile
export const MOCK_DOCTOR_PHONE = "+8801900000002"; // a verified, emergency-enabled synthetic doctor
export const MOCK_VERIFIER_PHONE = "+8801900000004"; // a verified synthetic verifier (CHW)
export const MOCK_REVIEWER_PHONE = "+8801900000005"; // a synthetic clinical reviewer
export const MOCK_ADMIN_PHONE = "+8801900000006"; // a synthetic admin
export const MOCK_RED_FLAG = "SYNTH-RED-FLAG"; // the mock routes a message containing this to the emergency card
