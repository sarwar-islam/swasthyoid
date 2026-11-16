import type { ReviewedText } from "../api/types";

// The ONLY place the frontend holds clinical wording. Every entry must be written or approved by the clinical reviewer (FRD
// invariant 2, M7: "first-aid cards are static and clinician-reviewed"; emergency messages are clinician-approved). The reviewer
// is not named yet (FRD question 7), so each entry is a REVIEWER-PENDING placeholder that says so on screen. Do not replace a
// placeholder with your own medical text: change `status` to "approved" only with the reviewer's signed wording.

const pending = (en: string, bn: string): ReviewedText =>
  ({ status: "REVIEWER-PENDING", en: `[REVIEWER-PENDING] ${en}`, bn: `[রিভিউয়ার-অনুমোদন বাকি] ${bn}` });

/** The emergency card's message, shown with the 999 call button. */
export const EMERGENCY_MESSAGE: ReviewedText = pending("Approved emergency message goes here.", "অনুমোদিত জরুরি বার্তা এখানে বসবে।");

/** Static first-aid cards (M7). Titles and steps come from the reviewer. */
export const FIRST_AID_CARDS: Array<{ id: string; title: ReviewedText; steps: ReviewedText[] }> = [1, 2, 3].map((n) => ({
  id: `card-${n}`,
  title: pending(`First-aid card ${n} title`, `প্রাথমিক চিকিৎসা কার্ড ${n}-এর শিরোনাম`),
  steps: [pending("Step 1 from the approved card", "অনুমোদিত কার্ডের ধাপ ১"), pending("Step 2 from the approved card", "অনুমোদিত কার্ডের ধাপ ২")],
}));
