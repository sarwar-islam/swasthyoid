import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MOCK_CODE, MOCK_PHONE, mockTransport } from "../../api/mock";
import type { ApiRequest, Transport } from "../../api/client";
import { axeViolations, renderApp } from "../../test-utils";

afterEach(() => {
  cleanup();
  localStorage.clear();
});

const type = (label: RegExp | string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const click = (name: RegExp | string) => fireEvent.click(screen.getByRole("button", { name }));

/** The mock, recording every request. */
function spy() {
  const inner = mockTransport();
  const seen: ApiRequest[] = [];
  const transport: Transport = (r) => {
    seen.push(r);
    return inner(r);
  };
  return { seen, transport };
}

describe("M1 sign-in", () => {
  it("a signed-out visitor is sent to the login page", () => {
    renderApp("/patient/timeline");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("লগইন");
  });

  it("a registered patient signs in with a code typed in Bangla digits, and lands home with the Health ID", async () => {
    const { seen, transport } = spy();
    renderApp("/patient/login", { transport });
    type("মোবাইল নম্বর", "+৮৮০১৭০০০০০০০১");
    click("কোড পাঠান");
    await screen.findByLabelText("এককালীন কোড");
    type("এককালীন কোড", "১২৩৪৫৬");
    click("লগইন করুন");
    expect(await screen.findByText("SID-4827190356")).toBeTruthy();
    const verify = seen.find((r) => r.path === "/auth/otp/verify")!.body as Record<string, string>;
    expect([verify.phone, verify.code, verify.account]).toEqual([MOCK_PHONE, MOCK_CODE, "patient"]); // ASCII on the wire
  });

  it("a new patient is asked for a profile, and a new code is sent with it", async () => {
    const { seen, transport } = spy();
    renderApp("/patient/login", { lang: "en", transport });
    type("Mobile number", "+8801799999999");
    click("Send code");
    type(await screen.findByLabelText("One-time code") && "One-time code", MOCK_CODE);
    click("Sign in");
    await screen.findByText(/You're new here/);
    type("Full name", "Synthetic Person");
    type("Date of birth", "1990-01-01");
    click("Send a new code with these details");
    type(await screen.findByLabelText("One-time code") && "One-time code", MOCK_CODE);
    click("Sign in");
    await screen.findByText("Your Health ID");
    expect(seen.filter((r) => r.path === "/auth/otp/request")).toHaveLength(2);
    expect((seen.filter((r) => r.path === "/auth/otp/verify").at(-1)!.body as { profile: object }).profile)
      .toMatchObject({ name: "Synthetic Person", dob: "1990-01-01", sex: "F" });
  });

  it("a wrong code says so, in words, next to the form", async () => {
    renderApp("/patient/login", { lang: "en" });
    type("Mobile number", MOCK_PHONE);
    click("Send code");
    type(await screen.findByLabelText("One-time code") && "One-time code", "000000");
    click("Sign in");
    expect((await screen.findByRole("alert")).textContent).toMatch("That code is wrong or has expired.");
  });
});

describe("M2 capture", () => {
  const pick = (names: string[]) => fireEvent.change(screen.getByLabelText(/Page photos/),
    { target: { files: names.map((n) => new File(["synthetic"], n, { type: "image/png" })) } });

  it("a poor page gets the approved Bangla guidance, and 'upload anyway' sends the flag and opens the document", async () => {
    const { seen, transport } = spy();
    renderApp("/patient/capture", { signedIn: true, transport });
    await screen.findByText("আপনার নথি");
    fireEvent.change(screen.getByLabelText(/পাতার ছবি/), { target: { files: [new File(["x"], "page-blur.png", { type: "image/png" })] } });
    click(/আপলোড করুন/);
    expect(await screen.findByText("ছবিটি ঝাপসা হয়েছে। ক্যামেরা স্থির রেখে আবার পরিষ্কার ছবি তুলুন।")).toBeTruthy();
    click("তবুও আপলোড করুন");
    expect(await screen.findByText("স্বয়ংক্রিয়ভাবে পড়ার ব্যবস্থা এখনো চালু হয়নি। আপনি নিজে তথ্যগুলো লিখে দিতে পারেন।")).toBeTruthy();
    const uploads = seen.filter((r) => r.path === "/documents" && r.method === "POST");
    expect(uploads.map((r) => (r.body as FormData).get("upload_anyway"))).toEqual(["false", "true"]);
    expect(uploads.every((r) => r.headers["Idempotency-Key"])).toBe(true);
  });

  it("retake clears the photos instead of uploading", async () => {
    renderApp("/patient/capture", { lang: "en", signedIn: true });
    pick(["blur.png"]);
    click(/Upload/);
    await screen.findByText("Some page photos didn't come out well");
    click("Retake photos");
    expect(screen.queryByText("Some page photos didn't come out well")).toBeNull();
    expect((screen.getByLabelText(/Page photos/) as HTMLInputElement).value).toBe("");
  });

  it("lists the patient's documents with their state", async () => {
    renderApp("/patient/capture", { lang: "en", signedIn: true });
    const list = within((await screen.findByText("Your documents")).closest("section")!);
    expect((await list.findAllByRole("link")).length).toBe(4);
    expect(list.getByText("Needs checking")).toBeTruthy();
  });
});

describe("M3 verification", () => {
  it("highlights low-confidence and unread fields with words, never colour alone, and pre-fills the raw reading", async () => {
    renderApp("/patient/documents/d-review", { lang: "en", signedIn: true });
    const doctor = (await screen.findByLabelText("Doctor's name")) as HTMLInputElement;
    expect(doctor.value).toBe("Dr. Synthetic Prescriber"); // raw reading, below 0.85, to be checked
    expect(doctor.closest(".field")!.className).toContain("low");
    expect(screen.getByText("Low confidence (0.71) · compare with the photo")).toBeTruthy();
    expect(screen.getByText("Couldn't be read properly · type it in")).toBeTruthy(); // follow_up_date: invalid_date
    expect((screen.getByLabelText("Prescription date") as HTMLInputElement).value).toBe("12/11/2026"); // shown day first
    expect(screen.getByLabelText("Prescription date").closest(".field")!.className).not.toContain("low");
    expect(screen.getAllByRole("group", { name: /Medicine \d/ })).toHaveLength(2);
  });

  it("confirm sends the reviewed fields, then the document is verified and its events reach the timeline", async () => {
    const { seen, transport } = spy();
    renderApp("/patient/documents/d-review", { lang: "en", signedIn: true, transport });
    type(await screen.findByLabelText("Doctor's name") && "Doctor's name", "Dr. Checked Synthetic");
    click("All correct, confirm");
    expect(await screen.findByText(/Confirmed. The details are now on your timeline./)).toBeTruthy();
    const review = seen.find((r) => r.method === "PUT")!.body as { fields: Record<string, unknown> };
    expect(review.fields.prescriber_name).toBe("Dr. Checked Synthetic");
    expect(review.fields.diagnosis_text).toBeNull(); // empty boxes are sent as null, never as ""
    expect(seen.map((r) => `${r.method} ${r.path}`)).toContain("POST /documents/d-review/confirm");
    fireEvent.click(screen.getByRole("link", { name: "View timeline" }));
    expect(await screen.findByText("Dr. Checked Synthetic")).toBeTruthy();
  });

  it("reject asks first; cancelling changes nothing", async () => {
    const { seen, transport } = spy();
    renderApp("/patient/documents/d-review", { lang: "en", signedIn: true, transport });
    click(await screen.findByRole("button", { name: "Reject this document" }) && "Reject this document");
    const dialog = screen.getByRole("alertdialog");
    expect(document.activeElement?.textContent).toBe("No, go back"); // focus starts on the safe choice
    fireEvent.click(within(dialog).getByRole("button", { name: "No, go back" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(seen.some((r) => r.path.endsWith("/reject"))).toBe(false);
  });

  it("a failed extraction offers retry and manual entry; an uploaded one offers manual entry", async () => {
    renderApp("/patient/documents/d-failed", { lang: "en", signedIn: true });
    expect(await screen.findByRole("button", { name: "Try reading again" })).toBeTruthy();
    click("Enter it yourself");
    expect(await screen.findByText("Check against the photo")).toBeTruthy();
  });

  it("never shows a safety alert to the patient", async () => {
    renderApp("/patient/documents/d-review", { lang: "en", signedIn: true });
    await screen.findByText("Check against the photo");
    expect(document.body.textContent).not.toMatch(/interaction|safety alert|conflict|override/i);
  });
});

describe("M4 timeline", () => {
  it("labels every entry's provenance, hides corrected versions under history, and filters self-reported entries", async () => {
    renderApp("/patient/timeline", { lang: "en", signedIn: true });
    await screen.findAllByRole("article");
    expect(screen.getAllByRole("article")).toHaveLength(3); // e-bp-1 is shown only inside e-bp-2's history
    expect(screen.getByText("Corrected (version 2)")).toBeTruthy();
    expect(screen.getByText("Correction history")).toBeTruthy();
    fireEvent.click(screen.getByLabelText("Self-reported"));
    const reported = screen.getAllByRole("article");
    expect(reported).toHaveLength(1);
    expect(within(reported[0]).getByText("Patient-reported · not verified")).toBeTruthy();
    expect(within(reported[0]).queryByText("Verified from a document")).toBeNull();
  });

  it("a verified entry links to its source document", async () => {
    renderApp("/patient/timeline", { lang: "en", signedIn: true });
    const links = await screen.findAllByRole("link", { name: "View the source document" });
    expect(links[0].getAttribute("href")).toBe("/patient/documents/d-verified");
  });
});

describe("M1/C1 Consent Center", () => {
  it("revoking asks first, then stops access and records it in the list", async () => {
    const { seen, transport } = spy();
    renderApp("/patient/consent", { lang: "en", signedIn: true, transport });
    click(await screen.findByRole("button", { name: "Stop access" }) && "Stop access");
    expect(screen.getByRole("alertdialog").textContent).toMatch("Stop ডা. সিনথেটিক চিকিৎসক's access now?");
    click("Yes, stop it");
    expect(await screen.findByText("Access stopped.")).toBeTruthy();
    expect(seen.some((r) => r.method === "POST" && r.path === "/consents/c-active/revoke")).toBe(true);
    await waitFor(() => expect(screen.getByText("No doctor has access right now.")).toBeTruthy());
  });

  it("a pending doctor request explains the code, and caregiver requests can be approved", async () => {
    renderApp("/patient/consent", { lang: "en", signedIn: true });
    expect(await screen.findByText(/wants to see your record\. If you agree, tell only them the code/)).toBeTruthy();
    expect(screen.getByText(/phone …0042\) asks for 30 days: upload documents, view timeline/)).toBeTruthy();
    click("Allow");
    await waitFor(() => expect(screen.queryByRole("button", { name: "Allow" })).toBeNull());
    expect(screen.getAllByRole("button", { name: "Stop access" })).toHaveLength(2); // doctor + the now-active caregiver
  });

  it("cloud AI cannot be switched on, and says why", async () => {
    renderApp("/patient/consent", { lang: "en", signedIn: true });
    const toggle = (await screen.findAllByRole("switch"))[0] as HTMLInputElement;
    expect([toggle.checked, toggle.disabled]).toEqual([false, true]);
    expect(screen.getByText(/this decision is still open/)).toBeTruthy();
  });

  it("access history shows allowed and blocked reads", async () => {
    renderApp("/patient/consent", { lang: "en", signedIn: true });
    const history = within((await screen.findByText("Who saw your information, and when")).closest("section")!);
    expect(await history.findByText("Viewed")).toBeTruthy();
    expect(history.getByText("Blocked")).toBeTruthy();
  });
});

describe("accessibility of every F1 page", () => {
  it.each(["/patient/login", "/patient", "/patient/capture", "/patient/documents/d-review", "/patient/timeline", "/patient/consent"])(
    "%s has no axe violations once loaded", async (path) => {
      const { container } = renderApp(path, { signedIn: path !== "/patient/login" });
      await screen.findAllByRole("heading", { level: 1 });
      await waitFor(() => expect(screen.queryByRole("status", { name: "" })?.textContent ?? "").not.toBe("লোড হচ্ছে…"));
      expect(await axeViolations(container)).toEqual([]);
    });
});
