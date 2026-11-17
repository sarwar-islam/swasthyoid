# Bangla UI copy for review

Generated from `web/src/i18n/strings.ts` (709 strings). Do not edit the strings here: reviewers mark the
**Review** column (OK, or the suggested Bangla), and the changes are made in `strings.ts`, then this file is generated again.

- **Native-language review:** every row. Plain, polite Bangla (আপনি form) for patients with low literacy; no ASCII digits
  (numbers are filled in at run time in Bangla digits); placeholders in braces, such as `{name}`, stay as they are.
- **Clinical review (clinical reviewer, FRD question 7):** rows in the groups `emergency`, `vitals`, `triage`, `firstAid`,
  `rem`, `al`, `th`, `reviewer` and any row that tells a patient what to do about their health. Clinical messages shown from the
  server (escalation, red flags, rule explanations) are not here: they come from the reviewer-approved M6 registry and
  `web/src/content/reviewerPending.ts`, and stay REVIEWER-PENDING until signed off.
- Brand and technical terms kept in Latin script on purpose: SwasthyoID, Health ID, SID, QR, SMS, OTP, BMDC, OCR, mmHg, mmol/L.

## Groups

[`app`](#app) (2) · [`a11y`](#a11y) (2) · [`lang`](#lang) (2) · [`theme`](#theme) (4) · [`emergency`](#emergency) (6) · [`portal`](#portal) (10) · [`nav`](#nav) (18) · [`common`](#common) (8) · [`err`](#err) (60) · [`login`](#login) (18) · [`home`](#home) (12) · [`doc`](#doc) (4) · [`status`](#status) (6) · [`capture`](#capture) (14) · [`q`](#q) (5) · [`docpage`](#docpage) (8) · [`verify`](#verify) (17) · [`f`](#f) (24) · [`tl`](#tl) (17) · [`prov`](#prov) (2) · [`consent`](#consent) (23) · [`cat`](#cat) (6) · [`cloud`](#cloud) (2) · [`history`](#history) (5) · [`more`](#more) (16) · [`reviewer`](#reviewer) (1) · [`vitals`](#vitals) (32) · [`triage`](#triage) (7) · [`firstAid`](#firstAid) (1) · [`rem`](#rem) (22) · [`profile`](#profile) (19) · [`dstatus`](#dstatus) (7) · [`req`](#req) (15) · [`open`](#open) (3) · [`bar`](#bar) (4) · [`ws`](#ws) (7) · [`sum`](#sum) (17) · [`chk`](#chk) (19) · [`srch`](#srch) (4) · [`al`](#al) (17) · [`cred`](#cred) (6) · [`bg`](#bg) (11) · [`dview`](#dview) (1) · [`care`](#care) (22) · [`vf`](#vf) (15) · [`rule`](#rule) (39) · [`bgr`](#bgr) (16) · [`cr`](#cr) (14) · [`catalog`](#catalog) (16) · [`audit`](#audit) (23) · [`staff`](#staff) (13) · [`role`](#role) (6) · [`met`](#met) (17) · [`qr`](#qr) (8) · [`pqr`](#pqr) (12) · [`inbox`](#inbox) (11) · [`th`](#th) (13)

## app

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `app.name` | SwasthyoID | SwasthyoID |  |
| `app.synthetic` | শুধু সিনথেটিক ডেটা · চিকিৎসা পরামর্শ নয় | Synthetic data only · not medical advice |  |

## a11y

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `a11y.skip` | মূল অংশে যান | Skip to main content |  |
| `a11y.mainNav` | প্রধান মেনু | Main menu |  |

## lang

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `lang.switch` | English | বাংলা |  |
| `lang.switchLabel` | ভাষা বদলান: English | Change language: বাংলা |  |

## theme

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `theme.label` | রং | Theme |  |
| `theme.system` | ডিভাইস অনুযায়ী | Device |  |
| `theme.light` | হালকা | Light |  |
| `theme.dark` | গাঢ় | Dark |  |

## emergency

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `emergency.bar` | জরুরি সাহায্য · ৯৯৯ | Emergency help · 999 |  |
| `emergency.title` | জরুরি সাহায্য | Emergency help |  |
| `emergency.call` | ৯৯৯-এ ফোন করুন | Call 999 |  |
| `emergency.open` | জরুরি কার্ড খুলুন | Open the emergency card |  |
| `emergency.firstAid` | প্রাথমিক চিকিৎসার কার্ড দেখুন | View first-aid cards |  |
| `emergency.seekCare` | নিকটস্থ স্বাস্থ্যকেন্দ্রে যোগাযোগ করুন। | Contact your nearest health facility. |  |

## portal

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `portal.choose` | পোর্টাল বেছে নিন | Choose a portal |  |
| `portal.devNote` | ডেভেলপমেন্ট পাতা। লগইন পরের ধাপে আসবে। | Development page. Sign-in arrives in F1. |  |
| `portal.patient` | রোগী | Patient |  |
| `portal.patient.desc` | নথি, টাইমলাইন, সম্মতি, ভাইটালস | Documents, timeline, consent, vitals |  |
| `portal.doctor` | ডাক্তার | Doctor |  |
| `portal.doctor.desc` | সম্মতি নিয়ে সারাংশ ও নিরাপত্তা সতর্কতা | Summary and safety alerts under consent |  |
| `portal.verifier` | যাচাইকারী / স্বাস্থ্যকর্মী | Verifier / CHW |  |
| `portal.verifier.desc` | রোগীর উপস্থিতিতে নথি তোলা ও যাচাই | Capture and verify with the patient present |  |
| `portal.console` | রিভিউয়ার ও অ্যাডমিন | Reviewer and admin |  |
| `portal.console.desc` | অনুমোদন, নিয়ম, অডিট | Approvals, rules, audit |  |

## nav

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `nav.home` | হোম | Home |  |
| `nav.timeline` | টাইমলাইন | Timeline |  |
| `nav.capture` | নথি তুলুন | Capture |  |
| `nav.consent` | সম্মতি | Consent |  |
| `nav.more` | আরও | More |  |
| `nav.patients` | রোগী খুঁজুন | Find patient |  |
| `nav.alerts` | নিরাপত্তা সতর্কতা | Safety alerts |  |
| `nav.breakglass` | জরুরি প্রবেশ | Emergency access |  |
| `nav.credentials` | আমার নিবন্ধন | My registration |  |
| `nav.queue` | যাচাই সারি | Verification queue |  |
| `nav.approvals` | নিবন্ধন অনুমোদন | Credential approvals |  |
| `nav.rules` | নিয়ম রেজিস্ট্রি | Rule registry |  |
| `nav.reviews` | জরুরি প্রবেশ পর্যালোচনা | Break-glass reviews |  |
| `nav.audit` | অডিট লগ | Audit log |  |
| `nav.metrics` | ওয়ার্কার মেট্রিক | Worker metrics |  |
| `nav.catalog` | ওষুধের তালিকা আমদানি | Drug catalog import |  |
| `nav.staff` | কর্মী অ্যাকাউন্ট | Staff accounts |  |
| `nav.inbox` | বিজ্ঞপ্তি | Notifications |  |

## common

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `common.loading` | লোড হচ্ছে… | Loading… |  |
| `common.error` | কিছু একটা ভুল হয়েছে। আবার চেষ্টা করুন। | Something went wrong. Try again. |  |
| `common.retry` | আবার চেষ্টা করুন | Try again |  |
| `common.cancel` | না, ফিরে যান | No, go back |  |
| `common.signOut` | লগআউট | Sign out |  |
| `common.page` | পাতা {n} | Page {n} |  |
| `common.mockMode` | ডেমো মোড: সব তথ্য কাল্পনিক। কোড {code} | Demo mode: all data is synthetic. Code {code} |  |
| `common.reasonRequired` | কারণ লিখুন। | Write a reason. |  |

## err

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `err.invalid_code` | কোডটি ভুল বা মেয়াদ শেষ। | That code is wrong or has expired. |  |
| `err.invalid_phone` | সঠিক মোবাইল নম্বর লিখুন। | Enter a valid mobile number. |  |
| `err.too_many_requests` | অনেকবার চেষ্টা হয়েছে। কিছুক্ষণ পরে আবার চেষ্টা করুন। | Too many tries. Wait a little and try again. |  |
| `err.network_unavailable` | সার্ভারে পৌঁছানো যাচ্ছে না। ইন্টারনেট সংযোগ দেখুন। | The server can't be reached. Check your internet connection. |  |
| `err.not_built` | এই অংশটি এখনো সার্ভারে চালু হয়নি। তাই এখানে কোনো তথ্য দেখানো হচ্ছে না। | This part isn't on the server yet, so nothing is shown here. |  |
| `err.not_revocable` | এই সম্মতি এখন সক্রিয় নয়। | This consent isn't active now. |  |
| `err.not_pending` | এই অনুরোধ আর খোলা নেই। | This request is no longer open. |  |
| `err.not_allowed_state` | নথিটি এখন এই অবস্থায় নেই। | The document isn't in that state now. |  |
| `err.retry_limit_reached` | এই নথি পড়ার সব চেষ্টা শেষ। হাতে লিখে দিন। | Every reading attempt for this document is used. Enter it by hand. |  |
| `err.not_retryable` | এই নথি আবার চেষ্টা করেও পড়া যাবে না। হাতে লিখে দিন। | Trying again won't read this document. Enter it by hand. |  |
| `err.extraction_in_progress` | নথিটি এখন পড়া হচ্ছে। একটু পরে আবার চেষ্টা করুন। | The document is being read right now. Try again shortly. |  |
| `err.invalid_document` | এক থেকে দশটি ছবি দিন। | Add one to ten images. |  |
| `err.image_file_too_large` | এই ছবির ফাইল খুব বড়। | This image file is too large. |  |
| `err.image_unsupported` | শুধু JPEG বা PNG ছবি দেওয়া যাবে। | Only JPEG or PNG images are accepted. |  |
| `err.image_undecodable` | এই ফাইলটি পড়া যাচ্ছে না, হয়তো নষ্ট। | This file can't be read; it may be damaged. |  |
| `err.image_too_large` | এই ছবিতে অনেক বেশি পিক্সেল। | This image has too many pixels. |  |
| `err.not_active` | এই অনুমতি এখন আর চালু নেই। রোগীর কাছে আবার অনুমতি চান। | This permission is no longer active. Ask the patient again. |  |
| `err.confirmation_required` | এই মানটি অস্বাভাবিক দেখাচ্ছে। নিশ্চিত করুন। | This value looks unusual. Confirm it. |  |
| `err.invalid_reading` | মান ও একক আবার দেখুন। | Check the value and the unit. |  |
| `err.invalid_contact` | প্রত্যেকের নাম ও সঠিক ফোন নম্বর দিন। | Give each person a name and a valid phone number. |  |
| `err.user_not_verified` | আপনার নিবন্ধন যাচাই হয়নি। | Your registration isn't verified. |  |
| `err.patient_not_found` | এই Health ID-তে কোনো রোগী নেই। | No patient has this Health ID. |  |
| `err.consent_required` | এই রোগীর সক্রিয় সম্মতি নেই। | There's no active consent for this patient. |  |
| `err.category_not_allowed` | রোগী এই অংশের অনুমতি দেননি। | The patient hasn't allowed this section. |  |
| `err.reason_required` | কারণ লিখুন। | Write a reason. |  |
| `err.not_open` | এই সতর্কতা আগেই দেখা হয়েছে। | This alert was already handled. |  |
| `err.credential_exists` | এই নম্বর আগেই নিবন্ধিত। | This number is already registered. |  |
| `err.invalid_credential` | নিবন্ধন নম্বর লিখুন। | Enter the registration number. |  |
| `err.emergency_not_enabled` | আপনার জরুরি প্রবেশাধিকার নেই। | You don't have emergency access. |  |
| `err.role_not_allowed` | আপনার এটি করার অনুমতি নেই। | You're not allowed to do this. |  |
| `err.user_suspended` | এই অ্যাকাউন্ট স্থগিত। | This account is suspended. |  |
| `err.invalid_categories` | অন্তত একটি অংশ বেছে নিন। | Choose at least one section. |  |
| `err.not_found` | খুঁজে পাওয়া যায়নি, অথবা দেখার অনুমতি নেই। | Not found, or you're not allowed to see it. |  |
| `err.unauthenticated` | আবার লগইন করুন। | Sign in again. |  |
| `err.review_required` | নিশ্চিত করার আগে ঘরগুলো দেখে সংরক্ষণ করুন। | Check the fields and save them before you confirm. |  |
| `err.date_required` | নথির তারিখ লিখুন। তারিখ ছাড়া নিশ্চিত করা যাবে না। | Enter the document's date. It can't be confirmed without one. |  |
| `err.invalid_date` | তারিখটি ঠিক নেই। দিন/মাস/বছর আকারে লিখুন। | That date isn't valid. Write it as day/month/year. |  |
| `err.unknown_field` | এই নথিতে এমন কোনো ঘর নেই। | This document has no such field. |  |
| `err.invalid_field` | একটি ঘরের লেখা ঠিক নেই। আবার দেখুন। | One field isn't valid. Check it again. |  |
| `err.invalid_fields` | তথ্যগুলো পড়া যায়নি। আবার চেষ্টা করুন। | The fields couldn't be read. Try again. |  |
| `err.not_configured` | এই সুবিধা এখনো চালু করা হয়নি। পরে আবার চেষ্টা করুন। | This isn't switched on yet. Try again later. |  |
| `err.invalid_request` | তথ্যগুলো আবার দেখুন। | Check the details and try again. |  |
| `err.console_no_signup` | এই নম্বরে কোনো কনসোল অ্যাকাউন্ট নেই। কনসোল অ্যাকাউন্ট শুধু অ্যাডমিন খুলতে পারেন। | There's no console account for this number. Only an admin can create console accounts. |  |
| `err.invalid_rule` | ধরন, তীব্রতা, সংজ্ঞা আর দুই ভাষার ব্যাখ্যা আবার দেখুন। | Check the type, severity, definition and both explanations. |  |
| `err.invalid_rule_definition` | এই ধরনের নিয়মে নির্ধারিত সংজ্ঞা (schema), দরকারি key আর তীব্রতা দিন। | For this rule type, use its schema definition with the required keys, and set a severity. |  |
| `err.query_required` | খোঁজার জন্য অন্তত একটি শব্দ লিখুন। | Type at least one word to search for. |  |
| `err.query_too_long` | খোঁজার লেখা ছোট করুন: সর্বোচ্চ ২০০ অক্ষর। | Shorten the search: at most 200 characters. |  |
| `err.draft_exists` | এই নিয়মের একটি খসড়া আগে থেকেই পর্যালোচনার অপেক্ষায়। | This rule already has a draft waiting for review. |  |
| `err.not_draft` | শুধু খসড়ার পর্যালোচনা করা যায়। | Only a draft can be reviewed. |  |
| `err.invalid_decision` | ন্যায্য বা অন্যায্য বেছে নিন। | Choose justified or unjustified. |  |
| `err.invalid_file` | খালি নয় এমন একটি CSV ফাইল বেছে নিন। | Choose a CSV file that isn't empty. |  |
| `err.source_required` | ফাইলটি কোথা থেকে এবং কোন শর্তে পাওয়া, তা লিখুন। | Say where the file came from and on what terms. |  |
| `err.invalid_catalog` | এই ফাইলটি তালিকা হিসেবে ব্যবহার করা যাচ্ছে না। কলাম ও ফাইলের ধরন দেখুন। | This file can't be used as a catalog. Check its columns and format. |  |
| `err.four_eyes` | নিজের লেখা খসড়া নিজে অনুমোদন করা যায় না। অন্য একজন রিভিউয়ারকে অনুমোদন করতে হবে। | You can't approve a draft you wrote. Another reviewer must approve it. |  |
| `err.invalid_vital_threshold` | ভাইটাল সীমার নিয়মে vital_type (bp বা glucose) ও তার সঙ্গে মেলে এমন unit দিন। | A vital threshold rule needs vital_type (bp or glucose) and a unit that fits it. |  |
| `err.invalid_role` | যাচাইকারী বা ক্লিনিক্যাল রিভিউয়ার বেছে নিন। | Choose verifier or clinical reviewer. |  |
| `err.invalid_name` | নাম লিখুন। | Enter the name. |  |
| `err.phone_exists` | এই নম্বরে আগে থেকেই একটি অ্যাকাউন্ট আছে। | This number already has an account. |  |
| `err.version_conflict` | অন্য কেউ এই সীমা বদলেছেন। আবার লোড করে দেখুন। | Someone else changed these thresholds. Reload and check them. |  |
| `err.invalid_threshold` | সার্ভার এই মান গ্রহণ করেনি। ক্ষেত্র ও মান আবার দেখুন। | The server did not accept these values. Check the fields and values. |  |

## login

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `login.title` | লগইন | Sign in |  |
| `login.intro` | আপনার মোবাইলে একটি এককালীন কোড পাঠানো হবে। | A one-time code will be sent to your mobile. |  |
| `login.expired` | আপনার সেশন শেষ হয়ে গেছে। আবার লগইন করুন। | Your session has ended. Please sign in again. |  |
| `login.phone` | মোবাইল নম্বর | Mobile number |  |
| `login.phoneHint` | যেমন ০১৭০০০০০০০১ | For example 01700000001 |  |
| `login.send` | কোড পাঠান | Send code |  |
| `login.code` | এককালীন কোড | One-time code |  |
| `login.codeHint` | SMS-এ পাওয়া ছয় অঙ্কের কোড | The six-digit code from the SMS |  |
| `login.verify` | লগইন করুন | Sign in |  |
| `login.changePhone` | নম্বর বদলান | Change number |  |
| `login.newHere` | আপনি নতুন। নিচের তথ্য দিন, তারপর নতুন কোড পাঠানো হবে। | You're new here. Fill in the details below, then a new code is sent. |  |
| `login.name` | পুরো নাম | Full name |  |
| `login.dob` | জন্ম তারিখ | Date of birth |  |
| `login.sex` | লিঙ্গ | Sex |  |
| `login.sex.F` | নারী | Female |  |
| `login.sex.M` | পুরুষ | Male |  |
| `login.sex.O` | অন্যান্য | Other |  |
| `login.register` | তথ্য দিয়ে নতুন কোড পাঠান | Send a new code with these details |  |

## home

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `home.welcome` | স্বাগতম, {name} | Welcome, {name} |  |
| `home.healthId` | আপনার Health ID | Your Health ID |  |
| `home.healthIdNote` | ডাক্তার আপনার রেকর্ড দেখতে চাইলে এই নম্বরটি বলুন। | Tell a doctor this number when they ask to see your record. |  |
| `home.copy` | নম্বর কপি করুন | Copy number |  |
| `home.copied` | কপি হয়েছে | Copied |  |
| `home.healthIdMissing` | Health ID এখন দেখানো যাচ্ছে না। | Your Health ID can't be shown right now. |  |
| `home.todo` | আপনার করণীয় | To do |  |
| `home.toVerify` | যাচাই বাকি নথি: {n} | Documents to check: {n} |  |
| `home.toConsent` | অপেক্ষায় থাকা অনুরোধ: {n} | Requests waiting: {n} |  |
| `home.nothing` | এখন কিছু করার নেই। | Nothing to do right now. |  |
| `home.capture` | নতুন নথি তুলুন | Capture a new document |  |
| `home.inbox` | নতুন বিজ্ঞপ্তি: {n} | New notifications: {n} |  |

## doc

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `doc.prescription` | প্রেসক্রিপশন | Prescription |  |
| `doc.lab_report` | ল্যাব রিপোর্ট | Lab report |  |
| `doc.discharge_summary` | হাসপাতালের ছাড়পত্র | Discharge summary |  |
| `doc.other` | অন্যান্য নথি | Other document |  |

## status

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `status.uploaded` | আপলোড হয়েছে | Uploaded |  |
| `status.extracting` | পড়া হচ্ছে | Being read |  |
| `status.needs_review` | যাচাই বাকি | Needs checking |  |
| `status.extraction_failed` | পড়া যায়নি | Couldn't be read |  |
| `status.verified` | যাচাই হয়েছে | Verified |  |
| `status.rejected` | বাতিল | Rejected |  |

## capture

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `capture.title` | নথি তুলুন | Capture a document |  |
| `capture.type` | নথির ধরন | Document type |  |
| `capture.files` | পাতার ছবি (এক থেকে দশটি, JPEG বা PNG) | Page photos (one to ten, JPEG or PNG) |  |
| `capture.tip` | কাগজটি সমান জায়গায় রাখুন, পর্যাপ্ত আলোতে পুরো পাতা ফ্রেমে নিন। | Lay the paper flat and fit the whole page in good light. |  |
| `capture.upload` | আপলোড করুন | Upload |  |
| `capture.uploading` | আপলোড হচ্ছে… | Uploading… |  |
| `capture.poor` | কিছু পাতার ছবি ভালো হয়নি | Some page photos didn't come out well |  |
| `capture.retake` | আবার ছবি তুলুন | Retake photos |  |
| `capture.anyway` | তবুও আপলোড করুন | Upload anyway |  |
| `capture.anywayNote` | তবুও আপলোড করলে নথিটি পড়ার চেষ্টা হবে; ভুল পড়লে আপনি যাচাইয়ের সময় ঠিক করবেন। | If you upload anyway, it's still read; you fix any mistakes when you check it. |  |
| `capture.yourDocs` | আপনার নথি | Your documents |  |
| `capture.noDocs` | এখনো কোনো নথি নেই। প্রথম প্রেসক্রিপশনটি তুলুন। | No documents yet. Capture your first prescription. |  |
| `capture.pick` | অন্তত একটি ছবি বেছে নিন। | Choose at least one photo. |  |
| `capture.sent` | নথি পাঠানো হয়েছে। | The document was sent. |  |

## q

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `q.image_blurry` | ঝাপসা | Blurry |  |
| `q.image_glare` | অতিরিক্ত আলো | Glare |  |
| `q.image_low_contrast` | লেখা অস্পষ্ট | Faint text |  |
| `q.image_skewed` | বাঁকা | Tilted |  |
| `q.image_too_small` | রেজোলিউশন কম | Low resolution |  |

## docpage

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `docpage.uploaded` | স্বয়ংক্রিয়ভাবে পড়ার ব্যবস্থা এখনো চালু হয়নি। আপনি নিজে তথ্যগুলো লিখে দিতে পারেন। | Automatic reading isn't switched on yet. You can enter the details yourself. |  |
| `docpage.extracting` | নথিটি পড়া হচ্ছে। একটু পরে আবার দেখুন। | The document is being read. Check back shortly. |  |
| `docpage.failed` | নথিটি পড়া যায়নি। আবার চেষ্টা করুন, অথবা নিজে লিখে দিন। | The document couldn't be read. Try again, or enter it yourself. |  |
| `docpage.verified` | এই নথি যাচাই হয়েছে এবং আপনার টাইমলাইনে আছে। | This document is verified and on your timeline. |  |
| `docpage.rejected` | এই নথি বাতিল করা হয়েছে। এটি টাইমলাইনে নেই। | This document was rejected. It isn't on your timeline. |  |
| `docpage.refresh` | আবার দেখুন | Check again |  |
| `docpage.manual` | নিজে লিখে দিন | Enter it yourself |  |
| `docpage.retry` | আবার পড়ার চেষ্টা করুন | Try reading again |  |

## verify

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `verify.title` | ছবির সাথে মিলিয়ে দেখুন | Check against the photo |  |
| `verify.intro` | প্রতিটি ঘর পাশের ছবির সাথে মিলিয়ে দেখুন, দরকার হলে ঠিক করুন। হলুদ চিহ্ন দেওয়া ঘরে পড়ার নিশ্চয়তা কম। | Compare every box with the photo beside it and fix anything wrong. Boxes marked in yellow were read with low confidence. |  |
| `verify.image` | নথির ছবি | Document photo |  |
| `verify.imageAlt` | পাতা {n}-এর ছবি | Photo of page {n} |  |
| `verify.low` | নিশ্চয়তা কম ({value}) · ছবির সাথে মিলিয়ে দেখুন | Low confidence ({value}) · compare with the photo |  |
| `verify.unread` | ঠিকভাবে পড়া যায়নি · নিজে লিখুন | Couldn't be read properly · type it in |  |
| `verify.medicine` | ওষুধ {n} | Medicine {n} |  |
| `verify.addMedicine` | আরেকটি ওষুধ যোগ করুন | Add another medicine |  |
| `verify.removeMedicine` | ওষুধ {n} সরান | Remove medicine {n} |  |
| `verify.nameMismatch` | নথিতে ছাপা নামটি আপনার নিবন্ধিত নামের সাথে মেলেনি। নথিটি আপনার কি না দেখে নিন। | The name printed on the document doesn't match your registered name. Make sure it's yours. |  |
| `verify.confirm` | সব ঠিক আছে, নিশ্চিত করুন | All correct, confirm |  |
| `verify.reject` | নথিটি বাতিল করুন | Reject this document |  |
| `verify.rejectAsk` | এই নথি বাতিল করবেন? এটি আপনার টাইমলাইনে যাবে না। | Reject this document? It won't go on your timeline. |  |
| `verify.rejectYes` | হ্যাঁ, বাতিল করুন | Yes, reject it |  |
| `verify.done` | নিশ্চিত হয়েছে। তথ্যগুলো এখন আপনার টাইমলাইনে। | Confirmed. The details are now on your timeline. |  |
| `verify.toTimeline` | টাইমলাইন দেখুন | View timeline |  |
| `verify.doneForPatient` | নিশ্চিত হয়েছে। তথ্যগুলো এখন রোগীর টাইমলাইনে আছে। | Confirmed. The details are now on the patient's timeline. |  |

## f

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `f.prescription_date` | প্রেসক্রিপশনের তারিখ | Prescription date |  |
| `f.prescriber_name` | ডাক্তারের নাম | Doctor's name |  |
| `f.prescriber_registration` | ডাক্তারের নিবন্ধন নম্বর | Doctor's registration number |  |
| `f.facility_name` | হাসপাতাল বা ক্লিনিক | Hospital or clinic |  |
| `f.diagnosis_text` | রোগনির্ণয় (যেমন লেখা আছে) | Diagnosis (as written) |  |
| `f.advice_text` | পরামর্শ | Advice |  |
| `f.follow_up_date` | আবার দেখানোর তারিখ | Follow-up date |  |
| `f.allergy_text` | অ্যালার্জি (যেমন লেখা আছে) | Allergy (as written) |  |
| `f.printed_patient_name` | নথিতে ছাপা রোগীর নাম | Patient name printed on the document |  |
| `f.report_date` | রিপোর্টের তারিখ | Report date |  |
| `f.lab_name` | ল্যাবের নাম | Lab name |  |
| `f.admission_date` | ভর্তির তারিখ | Admission date |  |
| `f.discharge_date` | ছাড়ার তারিখ | Discharge date |  |
| `f.name_as_written` | ওষুধের নাম (যেমন লেখা আছে) | Medicine name (as written) |  |
| `f.strength` | শক্তি | Strength |  |
| `f.form` | ধরন | Form |  |
| `f.dose_instruction` | খাওয়ার নিয়ম | How to take it |  |
| `f.duration` | কত দিন | For how long |  |
| `f.test_name` | পরীক্ষার নাম | Test name |  |
| `f.result` | ফলাফল | Result |  |
| `f.unit` | একক | Unit |  |
| `f.reference_range` | স্বাভাবিক সীমা | Reference range |  |
| `f.dateHint` | দিন/মাস/বছর | day/month/year |  |
| `f.reading` | রিডিং | Reading |  |

## tl

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `tl.title` | টাইমলাইন | Timeline |  |
| `tl.filter` | দেখান | Show |  |
| `tl.all` | সব | All |  |
| `tl.verified` | যাচাই করা | Verified |  |
| `tl.reported` | নিজের দেওয়া | Self-reported |  |
| `tl.empty` | এখানে এখনো কিছু নেই। | Nothing here yet. |  |
| `tl.source` | মূল নথি দেখুন | View the source document |  |
| `tl.corrected` | সংশোধিত (সংস্করণ {n}) | Corrected (version {n}) |  |
| `tl.history` | সংশোধনের ইতিহাস | Correction history |  |
| `tl.prescription` | প্রেসক্রিপশন | Prescription |  |
| `tl.medication` | ওষুধ | Medicine |  |
| `tl.vital_reading` | ভাইটাল রিডিং | Vital reading |  |
| `tl.visit` | ডাক্তার দেখানো | Visit |  |
| `tl.diagnosis` | রোগনির্ণয় | Diagnosis |  |
| `tl.lab_result` | ল্যাবের ফল | Lab result |  |
| `tl.allergy` | অ্যালার্জি | Allergy |  |
| `tl.follow_up` | ফলো-আপ | Follow-up |  |

## prov

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `prov.document_verified` | নথি থেকে যাচাইকৃত | Verified from a document |  |
| `prov.patient_reported` | রোগীর নিজের দেওয়া · যাচাই হয়নি | Patient-reported · not verified |  |

## consent

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `consent.title` | সম্মতি ও ইতিহাস | Consent and history |  |
| `consent.doctors` | ডাক্তার যারা আপনার রেকর্ড দেখতে পারেন | Doctors who can see your record |  |
| `consent.noDoctors` | এখন কোনো ডাক্তারের প্রবেশাধিকার নেই। | No doctor has access right now. |  |
| `consent.expires` | শেষ হবে: {date} | Ends: {date} |  |
| `consent.sees` | দেখতে পারেন: {what} | Can see: {what} |  |
| `consent.revoke` | প্রবেশ বন্ধ করুন | Stop access |  |
| `consent.revokeAsk` | {name}-এর প্রবেশ এখনই বন্ধ করবেন? পরের অনুরোধ থেকেই আটকে যাবে। | Stop {name}'s access now? Their next request is refused. |  |
| `consent.revokeYes` | হ্যাঁ, বন্ধ করুন | Yes, stop it |  |
| `consent.revoked` | প্রবেশ বন্ধ হয়েছে। | Access stopped. |  |
| `consent.pending` | অপেক্ষায় থাকা অনুরোধ | Waiting requests |  |
| `consent.pendingDoctor` | {name} আপনার রেকর্ড দেখতে চান। রাজি থাকলে SMS-এ পাওয়া কোডটি শুধু তাঁকেই বলুন। রাজি না থাকলে কোড বলবেন না। | {name} wants to see your record. If you agree, tell only them the code from the SMS. If you don't, don't share the code. |  |
| `consent.pendingDoctorQr` | {name} QR দিয়ে আপনার রেকর্ড দেখতে চেয়েছেন। রাজি থাকলে ডাক্তার সামনে থাকা অবস্থায় তাঁর QR স্ক্যান করুন বা কোডটি ওপরে লিখে অনুমতি দিন। রাজি না থাকলে কিছু করবেন না। | {name} asked by QR to see your record. If you agree, scan their QR or type their code above while they're with you. If you don't, do nothing. |  |
| `consent.caregivers` | পরিচর্যাকারী | Caregivers |  |
| `consent.caregiverAsk` | {name} (ফোন …{tail}) {days} দিনের জন্য অনুমতি চান: {what} | {name} (phone …{tail}) asks for {days} days: {what} |  |
| `consent.approve` | অনুমতি দিন | Allow |  |
| `consent.decline` | রাজি নই | Decline |  |
| `consent.past` | আগের সম্মতি | Earlier consents |  |
| `consent.status.expired` | মেয়াদ শেষ | Expired |  |
| `consent.status.revoked` | বন্ধ করা হয়েছে | Stopped |  |
| `consent.status.declined` | অস্বীকার করা হয়েছে | Declined |  |
| `consent.status.suspended` | স্থগিত | Suspended |  |
| `consent.status.active` | সক্রিয় | Active |  |
| `consent.status.pending` | অপেক্ষায় | Waiting |  |

## cat

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `cat.timeline` | টাইমলাইন | timeline |  |
| `cat.documents` | নথি | documents |  |
| `cat.safety` | নিরাপত্তা তথ্য | safety information |  |
| `cat.upload_documents` | নথি আপলোড | upload documents |  |
| `cat.view_documents` | নথি দেখা | view documents |  |
| `cat.view_timeline` | টাইমলাইন দেখা | view timeline |  |

## cloud

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `cloud.title` | ক্লাউড AI দিয়ে ছবি পড়া | Read photos with cloud AI |  |
| `cloud.note` | এখনো চালু করা যায় না: এ বিষয়ে সিদ্ধান্ত বাকি। আপনার ছবি এই যন্ত্রের বাইরে কোনো AI সেবায় পাঠানো হয় না। | Can't be switched on yet: this decision is still open. Your photos are never sent to an outside AI service. |  |

## history

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `history.title` | কে কখন আপনার তথ্য দেখেছেন | Who saw your information, and when |  |
| `history.empty` | এখনো কেউ দেখেননি। | Nobody has looked yet. |  |
| `history.allow` | অনুমতি পেয়েছেন | Allowed |  |
| `history.deny` | আটকানো হয়েছে | Blocked |  |
| `history.someone` | অজানা ব্যবহারকারী | Unknown user |  |

## more

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `more.title` | আরও | More |  |
| `more.vitals` | হোম ভাইটালস | Home vitals |  |
| `more.vitals.desc` | নিজে মাপা রক্তচাপ ও শর্করা লিখুন | Log your own blood pressure and glucose |  |
| `more.reminders` | রিমাইন্ডার | Reminders |  |
| `more.reminders.desc` | ওষুধ ও ফলো-আপ মনে করানো | Medicine and follow-up reminders |  |
| `more.help` | অসুস্থ বোধ করছেন? | Feeling unwell? |  |
| `more.help.desc` | কোন বিভাগে যাবেন, সেই নির্দেশনা | Guidance on which department to see |  |
| `more.firstAid` | প্রাথমিক চিকিৎসা | First aid |  |
| `more.firstAid.desc` | প্রাথমিক চিকিৎসার কার্ড | First-aid cards |  |
| `more.emergency` | জরুরি কার্ড | Emergency card |  |
| `more.emergency.desc` | ৯৯৯ ও জরুরি বার্তা | 999 and the emergency message |  |
| `more.profile` | জরুরি প্রোফাইল | Emergency profile |  |
| `more.profile.desc` | জরুরি অবস্থায় কী দেখা যাবে, তা বেছে নিন | Choose what an emergency doctor can see |  |
| `more.care` | যাঁদের দেখাশোনা করি | People I care for |  |
| `more.care.desc` | অনুমতি নিয়ে অন্য রোগীর নথি ও টাইমলাইন | Another patient's documents and timeline, with their permission |  |
| `more.inbox.desc` | সম্মতির অনুরোধ, পরিচর্যাকারী ও নিরাপত্তা বিজ্ঞপ্তি | Consent requests, caregivers and security notices |  |

## reviewer

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `reviewer.pending` | এই লেখা এখনো ক্লিনিক্যাল রিভিউয়ারের অনুমোদনের অপেক্ষায়। | This text is still waiting for the clinical reviewer's approval. |  |

## vitals

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `vitals.title` | হোম ভাইটালস | Home vitals |  |
| `vitals.intro` | আপনি নিজে মাপা রিডিং এখানে লিখবেন। এগুলো সবসময় রোগীর নিজের দেওয়া তথ্য হিসেবে দেখাবে। এটি রোগনির্ণয় নয়। | Log readings you measured yourself. They always show as patient-reported. This isn't a diagnosis. |  |
| `vitals.type` | কী মাপলেন | What did you measure |  |
| `vitals.bp` | রক্তচাপ | Blood pressure |  |
| `vitals.glucose` | রক্তে শর্করা | Blood glucose |  |
| `vitals.systolic` | উপরের সংখ্যা (সিস্টোলিক) | Top number (systolic) |  |
| `vitals.diastolic` | নিচের সংখ্যা (ডায়াস্টোলিক) | Bottom number (diastolic) |  |
| `vitals.value` | মান | Value |  |
| `vitals.unit` | একক | Unit |  |
| `vitals.context` | কখন মেপেছেন | When you measured |  |
| `vitals.ctx.home` | বাসায় | At home |  |
| `vitals.ctx.resting` | বিশ্রামের পর | After resting |  |
| `vitals.ctx.fasting` | খালি পেটে | Fasting |  |
| `vitals.ctx.post_meal` | খাওয়ার পর | After a meal |  |
| `vitals.ctx.random` | যেকোনো সময় | Any time |  |
| `vitals.when` | তারিখ ও সময় | Date and time |  |
| `vitals.save` | সংরক্ষণ করুন | Save |  |
| `vitals.correcting` | আগের রিডিংটি সংশোধন করছেন। আগেরটি ইতিহাসে থেকে যাবে। | You're correcting an earlier reading. The earlier one stays in the history. |  |
| `vitals.cancelCorrect` | সংশোধন বাদ দিন | Cancel correction |  |
| `vitals.numbersOnly` | শুধু সংখ্যা লিখুন। | Enter numbers only. |  |
| `vitals.confirmAsk` | এই মানটি অস্বাভাবিক দেখাচ্ছে। সংখ্যা ও একক আবার দেখুন। | This value looks unusual. Check the number and the unit again. |  |
| `vitals.confirmYes` | হ্যাঁ, মানটি ঠিক আছে | Yes, the value is right |  |
| `vitals.confirmFix` | ঠিক করি | Let me fix it |  |
| `vitals.saved` | সংরক্ষিত হয়েছে। | Saved. |  |
| `vitals.notEvaluated` | এই রিডিং দেখার অনুমোদিত নিয়ম এখনো নেই। কোনো উপসর্গ থাকলে ডাক্তারকে জানান। | There's no approved rule to check this reading yet. Tell a doctor about any symptoms. |  |
| `vitals.within` | রিডিংটি নির্ধারিত সীমার মধ্যে। কোনো উপসর্গ থাকলে ডাক্তারকে জানান। | The reading is within the configured range. Tell a doctor about any symptoms. |  |
| `vitals.flagged` | রিডিংটি নির্ধারিত সীমার বাইরে। | The reading is outside the configured range. |  |
| `vitals.critical` | জরুরি সতর্কতা | Urgent alert |  |
| `vitals.history` | আপনার রিডিং | Your readings |  |
| `vitals.none` | এখনো কোনো রিডিং নেই। | No readings yet. |  |
| `vitals.correct` | সংশোধন করুন | Correct |  |
| `vitals.older` | আগের সংস্করণ | Earlier versions |  |

## triage

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `triage.title` | অসুস্থ বোধ করছেন? | Feeling unwell? |  |
| `triage.notice` | এটি নির্দেশনা, রোগনির্ণয় নয়। জরুরি মনে হলে এখনই ৯৯৯-এ ফোন করুন। | This is guidance, not a diagnosis. If it feels like an emergency, call 999 now. |  |
| `triage.describe` | আপনার সমস্যা লিখুন | Describe your problem |  |
| `triage.start` | শুরু করুন | Start |  |
| `triage.again` | আবার শুরু করুন | Start again |  |
| `triage.suggestion` | যেখানে দেখাতে পারেন | Where you could go |  |
| `triage.demo` | ডেমো: জরুরি পথ দেখতে লিখুন {flag} | Demo: to see the emergency route, type {flag} |  |

## firstAid

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `firstAid.title` | প্রাথমিক চিকিৎসা | First aid |  |

## rem

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `rem.title` | রিমাইন্ডার | Reminders |  |
| `rem.intro` | রিমাইন্ডার শুধু প্রেসক্রিপশনে যা লেখা আছে তা মনে করিয়ে দেয়, কোনো ডোজের পরামর্শ দেয় না। আপনি চালু না করলে কোনো রিমাইন্ডার চলে না। | Reminders only repeat what the prescription says and never suggest a dose. Nothing runs until you switch it on. |  |
| `rem.proposed` | প্রস্তাবিত (আপনার সম্মতি দরকার) | Suggested (needs your OK) |  |
| `rem.active` | চালু | On |  |
| `rem.paused` | বিরতিতে | Paused |  |
| `rem.none` | এখানে কিছু নেই। | Nothing here. |  |
| `rem.kind.medicine` | ওষুধ | Medicine |  |
| `rem.kind.follow_up` | ফলো-আপ | Follow-up |  |
| `rem.kind.test` | পরীক্ষা | Test |  |
| `rem.times` | সময়: {times} | Times: {times} |  |
| `rem.source` | যেখান থেকে এসেছে তা দেখুন | View where it came from |  |
| `rem.confirm` | চালু করুন | Switch on |  |
| `rem.dismiss` | বাদ দিন | Dismiss |  |
| `rem.pause` | বিরতি দিন | Pause |  |
| `rem.resume` | আবার চালু করুন | Resume |  |
| `rem.stop` | পুরোপুরি বন্ধ করুন | Stop for good |  |
| `rem.stopAsk` | এই রিমাইন্ডার পুরোপুরি বন্ধ করবেন? আবার চালু করা যাবে না। | Stop this reminder for good? It can't be switched back on. |  |
| `rem.stopYes` | হ্যাঁ, বন্ধ করুন | Yes, stop it |  |
| `rem.taken` | খেয়েছি | Taken |  |
| `rem.skipped` | বাদ পড়েছে | Skipped |  |
| `rem.snoozed` | পরে মনে করান | Remind me later |  |
| `rem.last` | শেষ: {action}, {when} | Last: {action}, {when} |  |

## profile

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `profile.title` | জরুরি প্রোফাইল | Emergency profile |  |
| `profile.intro` | চালু করলে জরুরি অবস্থায় শুধু অনুমোদিত জরুরি ডাক্তার নিচে বেছে নেওয়া তথ্য দেখতে পারবেন, অল্প সময়ের জন্য। প্রতিবার দেখা হলে আপনাকে জানানো হবে। | When it's on, only an approved emergency doctor can see the fields you choose below, for a short time. You're told every time it's opened. |  |
| `profile.enable` | জরুরি প্রোফাইল চালু | Emergency profile on |  |
| `profile.fields` | কার্ডে কী থাকবে | What the card shows |  |
| `profile.f.blood_group` | রক্তের গ্রুপ | Blood group |  |
| `profile.f.allergies` | অ্যালার্জি | Allergies |  |
| `profile.f.active_medications` | চলমান ওষুধ | Current medicines |  |
| `profile.f.conditions` | দীর্ঘমেয়াদি রোগ | Long-term conditions |  |
| `profile.f.emergency_contacts` | জরুরি যোগাযোগ | Emergency contacts |  |
| `profile.noVerified` | যাচাই করা তথ্য নেই | Nothing verified yet |  |
| `profile.contacts` | জরুরি যোগাযোগের মানুষ | Emergency contact people |  |
| `profile.contactName` | নাম | Name |  |
| `profile.contactPhone` | ফোন নম্বর | Phone number |  |
| `profile.addContact` | আরেকজন যোগ করুন | Add another person |  |
| `profile.removeContact` | সরান | Remove |  |
| `profile.save` | সংরক্ষণ করুন | Save |  |
| `profile.saved` | জরুরি প্রোফাইল সংরক্ষিত হয়েছে। | Emergency profile saved. |  |
| `profile.preview` | জরুরি কার্ডে যা দেখা যাবে | What the emergency card shows |  |
| `profile.off` | প্রোফাইল বন্ধ: জরুরি কার্ডে কিছুই দেখা যাবে না। | Profile off: the emergency card shows nothing. |  |

## dstatus

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `dstatus.pending` | আপনার BMDC নিবন্ধন যাচাই বাকি। যাচাই না হওয়া পর্যন্ত রোগীর সম্মতি চাইতে পারবেন না। | Your BMDC registration is waiting for verification. You can't request patient consent until it's verified. |  |
| `dstatus.none` | আপনার BMDC নিবন্ধন নম্বর জমা দিন। যাচাই না হওয়া পর্যন্ত রোগীর সম্মতি চাইতে পারবেন না। | Submit your BMDC registration number. You can't request patient consent until it's verified. |  |
| `dstatus.suspended` | আপনার অ্যাকাউন্ট স্থগিত। সব সক্রিয় প্রবেশাধিকার বন্ধ। | Your account is suspended. All active access is stopped. |  |
| `dstatus.toCredentials` | নিবন্ধন দেখুন | View registration |  |
| `dstatus.label.pending` | যাচাই বাকি | Waiting for verification |  |
| `dstatus.label.verified` | যাচাই হয়েছে | Verified |  |
| `dstatus.label.suspended` | স্থগিত | Suspended |  |

## req

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `req.title` | রোগীর সম্মতি চান | Request patient consent |  |
| `req.healthId` | রোগীর Health ID | Patient's Health ID |  |
| `req.healthIdHint` | রোগী তাঁর অ্যাপে যে নম্বরটি দেখাবেন, SID দিয়ে শুরু | The number the patient shows in their app, starting with SID |  |
| `req.badId` | Health ID হলো SID- আর তারপর দশটি অঙ্ক। | A Health ID is SID- followed by ten digits. |  |
| `req.categories` | যা দেখতে চান | What you want to see |  |
| `req.send` | সম্মতির অনুরোধ পাঠান | Send consent request |  |
| `req.notVerified` | যাচাই না হওয়া পর্যন্ত অনুরোধ পাঠানো যাবে না। | Requests can't be sent until you're verified. |  |
| `req.codeTitle` | রোগীর কাছ থেকে কোড নিন | Get the code from the patient |  |
| `req.codeNote` | রোগীর ফোনে একটি এককালীন কোড গেছে। রোগী রাজি থাকলে কোডটি আপনাকে বলবেন। | A one-time code was sent to the patient's phone. If they agree, they'll tell you the code. |  |
| `req.code` | রোগীর বলা কোড | Code from the patient |  |
| `req.confirm` | কোড দিয়ে নিশ্চিত করুন | Confirm with the code |  |
| `req.cancel` | বাদ দিন | Cancel |  |
| `req.method` | রোগী কীভাবে নিশ্চিত করবেন | How the patient confirms |  |
| `req.method.otp` | SMS-এ যাওয়া কোড, রোগী আপনাকে বলবেন | Code by SMS, read out to you |  |
| `req.method.qr` | এই পর্দায় QR, রোগী নিজের অ্যাপে অনুমতি দেবেন | QR on this screen, approved in the patient's own app |  |

## open

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `open.title` | এই সেশনে খোলা রোগী | Patients opened in this session |  |
| `open.none` | এখনো কোনো রোগী নেই। উপরে সম্মতি চান। | No patients yet. Request consent above. |  |
| `open.view` | রেকর্ড খুলুন | Open record |  |

## bar

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `bar.patient` | রোগী | Patient |  |
| `bar.expires` | সম্মতি শেষ হতে বাকি {time} | Consent ends in {time} |  |
| `bar.expired` | সম্মতির মেয়াদ শেষ। আবার সম্মতি চাইতে হবে। | The consent has ended. Request consent again. |  |
| `bar.allowed` | অনুমতি: {what} | Allowed: {what} |  |

## ws

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `ws.record` | রোগীর রেকর্ড | Patient record |  |
| `ws.sections` | রেকর্ডের অংশ | Record sections |  |
| `ws.summary` | সারাংশ | Summary |  |
| `ws.search` | খুঁজুন | Search |  |
| `ws.notAllowed` | রোগী এই অংশ দেখার অনুমতি দেননি। | The patient hasn't allowed this section. |  |
| `ws.unknown` | এই সেশনে এই রোগীর সম্মতি নেই। রোগী খুঁজুন পাতা থেকে সম্মতি চান। | There's no consent for this patient in this session. Request it from Find patient. |  |
| `ws.thresholds` | ভাইটাল সীমা | Vital thresholds |  |

## sum

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `sum.template` | টেমপ্লেট সারাংশ: AI ছাড়া, যাচাই করা ঘটনা থেকে সরাসরি তৈরি | Template summary: built straight from verified events, no AI |  |
| `sum.llm` | AI লেখা সারাংশ: প্রতিটি বাক্য উৎস ঘটনার সাথে যাচাই করা | AI-written summary: every sentence checked against its source events |  |
| `sum.generated` | তৈরি: {date} | Generated: {date} |  |
| `sum.s.medications_recorded` | নথিভুক্ত ওষুধ | Medications recorded |  |
| `sum.s.allergies` | অ্যালার্জি | Allergies |  |
| `sum.s.diagnoses` | রোগনির্ণয় | Diagnoses |  |
| `sum.s.labs` | ল্যাব ফল, পরীক্ষা ও তারিখ অনুযায়ী | Lab results, by test and date |  |
| `sum.s.visits` | ভিজিট | Visits |  |
| `sum.s.follow_ups` | বাকি ফলো-আপ | Pending follow-ups |  |
| `sum.none` | নথিতে নেই | Nothing recorded |  |
| `sum.notRecorded` | রোগনির্ণয় এখানে তথ্য হিসেবে রাখা হয় না। মূল নথি দেখুন। | Diagnoses aren't kept as data here. See the source documents. |  |
| `sum.asWritten` | ওষুধ, মাত্রা ও ফল নথিতে যেমন লেখা, ঠিক তেমনই দেখানো হয়েছে। | Medicines, doses and results are shown exactly as written in the documents. |  |
| `sum.fallback` | AI সারাংশ যাচাইয়ে টেকেনি, তাই টেমপ্লেট সারাংশ দেখানো হচ্ছে। | An AI summary didn't pass the check, so the template summary is shown. |  |
| `sum.truncated` | আরও {n}টি দেখানো হয়নি। টাইমলাইনে দেখুন। | {n} more not shown. See the timeline. |  |
| `sum.reported` | রোগীর নিজের দেওয়া, যাচাই হয়নি | Reported by patient, not verified |  |
| `sum.reportedNote` | এগুলো রোগী নিজে মেপে লিখেছেন। যাচাই করা তথ্য হিসেবে ব্যবহার করবেন না। | The patient measured and entered these. Don't treat them as verified data. |  |
| `sum.cite` | উৎস ঘটনা {n} | Source event {n} |  |

## chk

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `chk.title` | যাচাই করা প্রেসক্রিপশনের নিরাপত্তা পরীক্ষা | Safety checks of verified prescriptions |  |
| `chk.none` | এখনো কোনো প্রেসক্রিপশন পরীক্ষা হয়নি। | No prescription has been checked yet. |  |
| `chk.status.queued` | পরীক্ষার অপেক্ষায় | Waiting to be checked |  |
| `chk.status.retrying` | কারিগরি কারণে পরীক্ষা হয়নি, আবার চেষ্টা চলছে | Not checked yet for a technical reason; trying again |  |
| `chk.status.completed` | পরীক্ষা হয়েছে: {n}টি সতর্কতা | Checked: {n} alerts |  |
| `chk.status.blocked` | পরীক্ষা হয়নি: নিরাপদে চালানো যায়নি | Not checked: the check couldn't run safely |  |
| `chk.status.failed` | পরীক্ষা হয়নি: কারিগরি সমস্যা। অ্যাডমিনকে জানান। | Not checked: technical failure. Tell the administrator. |  |
| `chk.reason.rule_load_error` | একটি অনুমোদিত নিয়ম পড়া যায়নি। | An approved rule couldn't be read. |  |
| `chk.reason.catalog_unavailable` | কোনো ওষুধের তালিকা চালু নেই। | No drug catalog is set up. |  |
| `chk.reason.infrastructure_error` | সিস্টেমের ত্রুটিতে পরীক্ষা থেমে গেছে। | A system error stopped the check. |  |
| `chk.unrecognised` | চেনা যায়নি, তাই পরীক্ষা হয়নি: | Not recognised, so not checked: |  |
| `chk.why.not_in_catalog` | তালিকায় নেই | not in the catalog |  |
| `chk.why.ambiguous` | একাধিক ওষুধের সাথে মেলে | matches more than one medicine |  |
| `chk.unnamed` | একটি ওষুধ (নাম লুকানো: অনুমতিতে টাইমলাইন নেই) | a medication (name hidden: the permission doesn't cover the timeline) |  |
| `chk.notRun` | যে পরীক্ষাগুলো এখনো চালানো যায় না: {list} | Checks that can't run yet: {list} |  |
| `chk.check.drug_disease` | ওষুধ ও রোগ (রোগনির্ণয় রাখা হয় না) | drug and condition (diagnoses aren't recorded) |  |
| `chk.check.allergy_class` | ওষুধের শ্রেণি অনুযায়ী অ্যালার্জি | allergy by drug class |  |
| `chk.check.duplicate_class` | একই শ্রেণির ওষুধ দুবার | the same drug class twice |  |
| `chk.check.class_lookback` | একই শ্রেণির সাম্প্রতিক কোর্স | a recent course of the same class |  |

## srch

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `srch.label` | রেকর্ডে খুঁজুন | Search the record |  |
| `srch.hint` | শুধু রোগীর দেওয়া অনুমতির মধ্যে খোঁজা হয়। | Only what the patient allowed is searched. |  |
| `srch.none` | কিছু পাওয়া যায়নি। | Nothing found. |  |
| `srch.event` | ঘটনাটি টাইমলাইনে দেখুন | View the event on the timeline |  |

## al

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `al.none` | খোলা কোনো সতর্কতা নেই। | No open alerts. |  |
| `al.notDiagnosis` | সতর্কতা রোগনির্ণয় নয়, আর সতর্কতা না থাকা মানেও নিরাপদ নয়। | An alert is never a diagnosis, and no alert never means safe. |  |
| `al.rule` | নিয়ম | Rule |  |
| `al.sev.contraindicated` | কন্ট্রাইন্ডিকেটেড | Contraindicated |  |
| `al.sev.major` | গুরুতর | Major |  |
| `al.sev.moderate` | মাঝারি | Moderate |  |
| `al.sev.minor` | সামান্য | Minor |  |
| `al.evidence` | যে ঘটনা থেকে | Triggering events |  |
| `al.source` | যাচাই করা প্রেসক্রিপশন দেখুন | View the verified prescription |  |
| `al.ack` | স্বীকার করুন | Acknowledge |  |
| `al.override` | কারণসহ উপেক্ষা করুন | Override with a reason |  |
| `al.reason` | উপেক্ষার কারণ (বাধ্যতামূলক) | Reason for the override (required) |  |
| `al.reasonRequired` | উপেক্ষা করতে কারণ লিখুন। | Write a reason to override. |  |
| `al.submitOverride` | উপেক্ষা নিশ্চিত করুন | Confirm override |  |
| `al.acknowledged` | স্বীকার করা হয়েছে | Acknowledged |  |
| `al.overridden` | উপেক্ষা করা হয়েছে · কারণ: {reason} | Overridden · reason: {reason} |  |
| `al.allPatients` | এই সেশনে খোলা রোগীদের সতর্কতা | Alerts for patients opened in this session |  |

## cred

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `cred.title` | আমার নিবন্ধন | My registration |  |
| `cred.number` | BMDC নিবন্ধন নম্বর | BMDC registration number |  |
| `cred.submit` | যাচাইয়ের জন্য জমা দিন | Submit for verification |  |
| `cred.submitted` | জমা হয়েছে। একজন অ্যাডমিন যাচাই করবেন। | Submitted. An admin will verify it. |  |
| `cred.current` | জমা দেওয়া নম্বর | Submitted number |  |
| `cred.status` | অবস্থা | Status |  |

## bg

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `bg.title` | জরুরি প্রবেশ (break-glass) | Emergency access (break-glass) |  |
| `bg.intro` | শুধু অচেতন বা অক্ষম রোগীর জরুরি অবস্থায়। কারণ ও প্রতিষ্ঠান বাধ্যতামূলক। প্রবেশ অডিট হয়, রোগীকে অ্যাপে জানানো হয়, আর পরে পর্যালোচনা হয়। জরুরি যোগাযোগের মানুষকে জানানো এখনো চালু হয়নি। | Only for an unconscious or incapable patient in an emergency. A reason and a facility are required. Access is audited, the patient is told in the app, and every session is reviewed later. Telling the emergency contact is not built yet. |  |
| `bg.reason` | কারণ | Reason |  |
| `bg.facility` | প্রতিষ্ঠান | Facility |  |
| `bg.open` | জরুরি কার্ড খুলুন | Open the emergency card |  |
| `bg.required` | কারণ ও প্রতিষ্ঠান দুটোই লিখুন। | Write both a reason and a facility. |  |
| `bg.cardTitle` | জরুরি কার্ড | Emergency card |  |
| `bg.expires` | সেশন শেষ হতে বাকি {time} | Session ends in {time} |  |
| `bg.expired` | সেশন শেষ। কার্ড আর দেখানো হচ্ছে না। | The session has ended. The card is no longer shown. |  |
| `bg.noProfile` | রোগীর জরুরি প্রোফাইল চালু নেই। দেখানোর মতো কিছু নেই। | The patient's emergency profile is off. There's nothing to show. |  |
| `bg.end` | কার্ড বন্ধ করুন | Close the card |  |

## dview

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `dview.title` | নথির ছবি (শুধু দেখা) | Document photos (view only) |  |

## care

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `care.title` | যাঁদের দেখাশোনা করি | People I care for |  |
| `care.intro` | রোগী যতটুকু অনুমতি দিয়েছেন, শুধু ততটুকুই এখানে করা যায়। রোগী যেকোনো সময় অনুমতি বন্ধ করতে পারেন। | You can do only what the patient allowed. The patient can stop your access at any time. |  |
| `care.none` | এখন কারও সক্রিয় অনুমতি নেই। | No one has given you active access right now. |  |
| `care.approved` | অনুমতি সক্রিয় হয়েছে। | Access is now active. |  |
| `care.until` | মেয়াদ {date} পর্যন্ত | Until {date} |  |
| `care.open` | {name}-এর রেকর্ড খুলুন | Open {name}'s record |  |
| `care.askTitle` | অনুমতি চান | Ask for access |  |
| `care.healthId` | রোগীর Health ID | Patient's Health ID |  |
| `care.scopes` | যে কাজের অনুমতি চান | What you ask to do |  |
| `care.days` | কত দিনের জন্য | For how many days |  |
| `care.daysHint` | এক থেকে নব্বই দিন। সাধারণত ত্রিশ দিন। | 1 to 90 days; usually 30. |  |
| `care.never` | পরিচর্যাকারী কখনো নথি যাচাই, সম্মতি দেওয়া বা বন্ধ করা, অথবা রোগীর প্রবেশ ইতিহাস দেখতে পারেন না। | A caregiver can never verify documents, grant or stop consent, or see the patient's access history. |  |
| `care.send` | অনুরোধ পাঠান | Send request |  |
| `care.sent` | অনুরোধ পাঠানো হয়েছে ({id})। রোগী অ্যাপে অনুমতি দিতে পারেন, অথবা তাঁর নিজের ফোনে আসা কোডটি আপনাকে বলতে পারেন। | Request sent ({id}). The patient can approve it in their app, or read you the code sent to their own phone. |  |
| `care.confirm` | কোড দিয়ে নিশ্চিত করুন | Confirm with the code |  |
| `care.actingFor` | আপনি {name}-এর হয়ে কাজ করছেন | You are acting for {name} |  |
| `care.back` | আমার তালিকায় ফিরুন | Back to my list |  |
| `care.noAccess` | এই রোগীর রেকর্ডে আপনার এখন কোনো সক্রিয় অনুমতি নেই। | You have no active access to this patient's record now. |  |
| `care.noScope` | রোগী এই কাজের অনুমতি দেননি। | The patient hasn't allowed this. |  |
| `care.documents` | নথি | Documents |  |
| `care.allDocs` | সব নথি | All documents |  |
| `care.upload` | এঁর নথি আপলোড | Upload for them |  |

## vf

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `vf.title` | রোগীর উপস্থিতিতে কাজ শুরু | Start with the patient present |  |
| `vf.intro` | রোগী সামনে আছেন এবং রাজি আছেন, তা নিশ্চিত হতে রোগীর নিজের ফোনে একটি কোড যাবে। রোগী কোডটি আপনাকে বলবেন। কোড ছাড়া কোনো নথি খোলা যায় না। | A code goes to the patient's own phone, to show the patient is here and agrees. The patient reads it out to you. Without the code, no document opens. |  |
| `vf.sendCode` | রোগীর ফোনে কোড পাঠান | Send a code to the patient's phone |  |
| `vf.codeNote` | রোগীর ফোনে একটি এককালীন কোড গেছে। রোগীকে কোডটি পড়ে শোনাতে বলুন। রোগী রাজি না থাকলে এখানেই থামুন। | A one-time code was sent to the patient's phone. Ask the patient to read it out. If the patient doesn't agree, stop here. |  |
| `vf.confirm` | কোড দিয়ে শুরু করুন | Start with the code |  |
| `vf.session` | চলমান সেশন | Current session |  |
| `vf.present` | রোগীর কোড দিয়ে শুরু | Started with the patient's code |  |
| `vf.left` | সেশন শেষ হতে বাকি {time} | Session ends in {time} |  |
| `vf.ended` | সেশন শেষ। আবার কাজ করতে রোগীর নতুন কোড লাগবে। | The session has ended. A new code from the patient is needed. |  |
| `vf.end` | সেশন শেষ করুন | End session |  |
| `vf.start` | নতুন সেশন শুরু করুন | Start a new session |  |
| `vf.noSession` | আগে রোগীর কোড দিয়ে একটি সেশন শুরু করুন। | First start a session with the patient's code. |  |
| `vf.timePending` | সেশনের সময়সীমা এখনো চূড়ান্ত নয় (রিভিউয়ার-অনুমোদন বাকি)। | The session time limit isn't final yet (REVIEWER-PENDING). |  |
| `vf.toCheck` | যাচাই বাকি নথি | Documents to check |  |
| `vf.notVerified` | আপনার অ্যাকাউন্ট এখনো অনুমোদিত হয়নি। অনুমোদনের আগে রোগীর সেশন শুরু করা যাবে না। | Your account isn't approved yet. You can't start a patient session until it is. |  |

## rule

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `rule.note` | শুধু অনুমোদিত নিয়ম চলে। নিয়মের বিষয়বস্তু ক্লিনিক্যাল রিভিউয়ারের লেখা; [রিভিউয়ার-অনুমোদন বাকি] চিহ্নিত সবকিছু শুধু জায়গা রাখা। | Only approved rules run. Rule content is written by the clinical reviewer; everything marked [REVIEWER-PENDING] is a placeholder. |  |
| `rule.filter` | নিয়মের ধরন | Rule type |  |
| `rule.allTypes` | সব ধরন | All types |  |
| `rule.draftTitle` | নতুন নিয়মের খসড়া | Draft a new rule |  |
| `rule.newVersionOf` | {id}-এর নতুন সংস্করণ | New version of {id} |  |
| `rule.type` | ধরন | Type |  |
| `rule.severity` | তীব্রতা | Severity |  |
| `rule.noSeverity` | প্রযোজ্য নয় | Not applicable |  |
| `rule.definition` | সংজ্ঞা (JSON) | Definition (JSON) |  |
| `rule.definitionHint` | ক্লিনিক্যাল রিভিউয়ারের লেখা ও স্বাক্ষর করা বিষয়বস্তু। অনুমোদনের আগে কিছুই চলে না। | Content written and signed by the clinical reviewer. Nothing runs before it is approved. |  |
| `rule.badJson` | সংজ্ঞাটি একটি JSON অবজেক্ট হতে হবে। | The definition must be a JSON object. |  |
| `rule.explanationBn` | ব্যাখ্যা (বাংলা) | Explanation (Bangla) |  |
| `rule.explanationEn` | ব্যাখ্যা (ইংরেজি) | Explanation (English) |  |
| `rule.saveDraft` | খসড়া সংরক্ষণ করুন | Save draft |  |
| `rule.saved` | খসড়া সংরক্ষিত। অনুমোদনের আগে এটি চলবে না। | Draft saved. It won't run until it is approved. |  |
| `rule.approved` | নিয়ম অনুমোদিত। আগের অনুমোদিত সংস্করণ আর চলবে না। | Rule approved. The earlier approved version no longer runs. |  |
| `rule.rejected` | খসড়া বাতিল হয়েছে। | Draft rejected. |  |
| `rule.none` | এই ধরনের কোনো নিয়ম নেই। | No rules of this type. |  |
| `rule.version` | সংস্করণ {n} | version {n} |  |
| `rule.by` | লিখেছেন {name}, {date} | Written by {name}, {date} |  |
| `rule.reviewedBy` | পর্যালোচনা {name}, {date} | reviewed by {name}, {date} |  |
| `rule.rejectedBecause` | বাতিলের কারণ: {reason} | Rejected because: {reason} |  |
| `rule.rejectReason` | বাতিলের কারণ | Reason for rejecting |  |
| `rule.reject` | বাতিল করুন | Reject |  |
| `rule.approve` | অনুমোদন দিন | Approve |  |
| `rule.newVersion` | নতুন সংস্করণের খসড়া | Draft a new version |  |
| `rule.approveAsk` | {id} সংস্করণ {n} অনুমোদন দেবেন? অনুমোদনের পর এটি চলবে, আগের সংস্করণ বন্ধ হবে। | Approve {id} version {n}? Once approved it runs, and the earlier version stops. |  |
| `rule.type.ddi` | ওষুধে-ওষুধে প্রতিক্রিয়া | Drug-drug interaction |  |
| `rule.type.allergy` | অ্যালার্জি | Allergy |  |
| `rule.type.duplicate` | একই চিকিৎসা দুবার | Duplicate therapy |  |
| `rule.type.drug_disease` | ওষুধ ও রোগ | Drug-disease |  |
| `rule.type.class_lookback` | সাম্প্রতিক একই শ্রেণির কোর্স | Recent same-class course |  |
| `rule.type.vital_threshold` | ভাইটালের সীমা | Vital threshold |  |
| `rule.type.red_flag` | বিপদচিহ্ন | Red flag |  |
| `rule.type.emergency_message` | জরুরি বার্তা | Emergency message |  |
| `rule.status.draft` | খসড়া | Draft |  |
| `rule.status.approved` | অনুমোদিত | Approved |  |
| `rule.status.rejected` | বাতিল | Rejected |  |
| `rule.status.superseded` | পুরোনো সংস্করণ | Superseded |  |

## bgr

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `bgr.intro` | প্রতিটি জরুরি প্রবেশ শেষ হলে এখানে আসে। কে, কেন, কোথায়, কখন আর কার্ডের কোন ঘর দেখানো হয়েছিল, শুধু তা দেখা যায়; রোগী বা তথ্যের মান নয়। | Every break-glass session comes here once it ends. You see who, why, where, when and which card fields were shown; never the patient or the values. |  |
| `bgr.pending` | পর্যালোচনা বাকি | Waiting for review |  |
| `bgr.nonePending` | পর্যালোচনা বাকি নেই। | Nothing is waiting for review. |  |
| `bgr.done` | পর্যালোচনা হয়েছে | Reviewed |  |
| `bgr.status.review_pending` | পর্যালোচনা বাকি | Waiting for review |  |
| `bgr.status.justified` | ন্যায্য | Justified |  |
| `bgr.status.unjustified` | অন্যায্য | Unjustified |  |
| `bgr.when` | সময় | When |  |
| `bgr.fields` | দেখানো ঘর | Fields shown |  |
| `bgr.noFields` | কোনো ঘর দেখানো হয়নি | No fields were shown |  |
| `bgr.note` | মন্তব্য | Note |  |
| `bgr.noteHint` | অন্যায্য হলে কারণ লেখা বাধ্যতামূলক। | Required when the access was not justified. |  |
| `bgr.justified` | ন্যায্য | Justified |  |
| `bgr.unjustified` | অন্যায্য | Unjustified |  |
| `bgr.noteWas` | মন্তব্য: {note} | Note: {note} |  |
| `bgr.suspended` | {name}-এর জরুরি প্রবেশাধিকার স্থগিত। | {name}'s emergency access is suspended. |  |

## cr

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `cr.intro` | অনুমোদনের আগে BMDC নিবন্ধন নম্বরটি মিলিয়ে দেখুন। জমা দেওয়া নথি এখানে এখনো দেখা যায় না। | Check the BMDC registration number before approving. The submitted document can't be viewed here yet. |  |
| `cr.pending` | অনুমোদন বাকি | Waiting for approval |  |
| `cr.nonePending` | অনুমোদন বাকি নেই। | Nothing is waiting for approval. |  |
| `cr.verified` | যাচাই হওয়া ডাক্তার | Verified doctors |  |
| `cr.noneVerified` | যাচাই হওয়া কোনো ডাক্তার নেই। | No verified doctors. |  |
| `cr.approve` | অনুমোদন দিন | Approve |  |
| `cr.approveAsk` | {name}-এর নিবন্ধন ({number}) অনুমোদন দেবেন? | Approve {name}'s registration ({number})? |  |
| `cr.approved` | {name}-এর নিবন্ধন অনুমোদিত। | {name}'s registration is approved. |  |
| `cr.reject` | বাতিল করুন | Reject |  |
| `cr.rejectReason` | বাতিলের কারণ | Reason for rejecting |  |
| `cr.rejected` | {name}-এর নিবন্ধন বাতিল হয়েছে। তিনি আবার জমা দিতে পারবেন। | {name}'s registration was rejected. They can submit again. |  |
| `cr.suspend` | স্থগিত করুন | Suspend |  |
| `cr.suspendReason` | স্থগিতের কারণ | Reason for suspending |  |
| `cr.suspended` | {name} স্থগিত। তাঁর সব সক্রিয় সম্মতিও স্থগিত। | {name} is suspended, and so are all their active consents. |  |

## catalog

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `catalog.licence` | ওষুধের তালিকার উৎস ও লাইসেন্স এখনো ঠিক হয়নি। প্রকৃত তালিকা আমদানি করবেন না; এই প্রোটোটাইপ পাঠানো ফাইল সংরক্ষণ করে না। | The drug catalog's source and licence aren't decided yet. Don't import a real catalog; this prototype keeps nothing it receives. |  |
| `catalog.file` | তালিকার ফাইল (CSV) | Catalog file (CSV) |  |
| `catalog.hint` | শুধু সিনথেটিক পরীক্ষার ফাইল। | Synthetic test files only. |  |
| `catalog.send` | আমদানির জন্য পাঠান | Send for import |  |
| `catalog.source` | ফাইলটি কোথা থেকে এবং কোন শর্তে পাওয়া | Where the file came from, and on what terms |  |
| `catalog.sourceHint` | যেমন: উৎস, লাইসেন্স বা অনুমতি, কবে নেওয়া। এটি ফাইলের পরিচয়ের সঙ্গে সংরক্ষিত থাকবে। | For example: the source, the licence or permission, when it was obtained. It is kept with the file's fingerprint. |  |
| `catalog.reportTitle` | যাচাইয়ের ফলাফল | Validation report |  |
| `catalog.validated` | {file} ({size} কিলোবাইট) যাচাই করা হয়েছে। | {file} ({size} KB) was validated. |  |
| `catalog.notStored` | ফাইলের কোনো তথ্য রাখা হয়নি; শুধু হ্যাশ, আকার, এই সংখ্যাগুলো আর উৎসের বিবরণ রাখা হয়েছে। কাজের তালিকা বদলায়নি। | None of the file's data was kept: only its hash, size, these counts and the source statement. The working catalog is unchanged. |  |
| `catalog.r.rows` | মোট সারি | Rows |  |
| `catalog.r.matchable` | মেলানো যায় এমন সারি | Rows that can be matched |  |
| `catalog.r.unmatchable` | ব্র্যান্ড বা জেনেরিক নাম নেই এমন সারি | Rows with no brand or generic name |  |
| `catalog.r.duplicate_groups` | হুবহু একই সারির দল | Groups of identical rows |  |
| `catalog.r.near_duplicate_groups` | প্রায় একই সারির দল | Groups of near-identical rows |  |
| `catalog.r.brands_with_several_generics` | একাধিক জেনেরিক নামের ব্র্যান্ড | Brands with several generic names |  |
| `catalog.r.products_with_several_manufacturers` | একাধিক প্রস্তুতকারকের পণ্য | Products with several manufacturers |  |

## audit

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `audit.intro` | শুধু মেটাডেটা: নাম, ফোন, আইপি, ডিভাইস বা চিকিৎসার তথ্য নেই। মানুষ ও রেকর্ড ছোট ছদ্মনাম নম্বরে দেখানো হয়। | Metadata only: no name, phone, IP address, device or clinical content. People and records appear as short pseudonymous references. |  |
| `audit.intact` | হ্যাশ চেইন অক্ষত: {n}টি এন্ট্রি যাচাই, {at}। | Hash chain intact: {n} entries checked, {at}. |  |
| `audit.broken` | হ্যাশ চেইন ভাঙা, এন্ট্রি {id} থেকে। এখনই তদন্ত করুন। | The hash chain is broken from entry {id}. Investigate now. |  |
| `audit.filters` | অডিট ছাঁকনি | Audit filters |  |
| `audit.action` | কাজের নাম শুরু হয় | Action starts with |  |
| `audit.actionHint` | যেমন timeline বা rule | For example timeline or rule |  |
| `audit.result` | ফল | Result |  |
| `audit.role` | ভূমিকা | Role |  |
| `audit.any` | যেকোনো | Any |  |
| `audit.apply` | দেখান | Show |  |
| `audit.none` | কোনো এন্ট্রি মেলেনি। | No entries match. |  |
| `audit.caption` | অডিট এন্ট্রি, নতুনটি আগে | Audit entries, newest first |  |
| `audit.at` | সময় | Time |  |
| `audit.actor` | কে | Who |  |
| `audit.purpose` | উদ্দেশ্য | Purpose |  |
| `audit.reason` | কারণ | Reason |  |
| `audit.patient` | রোগী | Patient |  |
| `audit.hashes` | আগের → এই হ্যাশ | Previous → this hash |  |
| `audit.prev` | আগের হ্যাশ, তারপর এই এন্ট্রির হ্যাশ: | Previous hash, then this entry's hash: |  |
| `audit.textHidden` | লেখা লুকানো | Text hidden |  |
| `audit.colAction` | কাজ | Action |  |
| `audit.allow` | অনুমোদিত | Allowed |  |
| `audit.deny` | প্রত্যাখ্যাত | Denied |  |

## staff

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `staff.intro` | যাচাইকারী আর ক্লিনিক্যাল রিভিউয়ারের অ্যাকাউন্ট এখানে খোলা হয়; রিভিউয়ার বা অ্যাডমিন নিজে নিবন্ধন করতে পারেন না। ডাক্তার অনুমোদন পান BMDC নিবন্ধন দিয়ে। | Verifier and clinical reviewer accounts are created here; nobody can register as a reviewer or admin. Doctors are approved through their BMDC registration. |  |
| `staff.pending` | অনুমোদন বাকি নিবন্ধন | Registrations waiting for approval |  |
| `staff.nonePending` | কোনো নিবন্ধন অনুমোদনের অপেক্ষায় নেই। | No registration is waiting for approval. |  |
| `staff.approveAsk` | {name} ({role})-এর অ্যাকাউন্ট অনুমোদন দেবেন? | Approve the account of {name} ({role})? |  |
| `staff.approved` | {name}-এর অ্যাকাউন্ট অনুমোদিত। | {name}'s account is approved. |  |
| `staff.addTitle` | নতুন কর্মী অ্যাকাউন্ট | New staff account |  |
| `staff.phoneHint` | এই নম্বরে এককালীন কোড দিয়ে লগইন হবে | They sign in with a one-time code sent to this number |  |
| `staff.add` | অ্যাকাউন্ট খুলুন | Create account |  |
| `staff.added` | {name}-এর অ্যাকাউন্ট খোলা হয়েছে। তিনি এখন লগইন করতে পারবেন। | {name}'s account is created. They can sign in now. |  |
| `staff.active` | সক্রিয় কর্মী | Active staff |  |
| `staff.noneActive` | সক্রিয় কোনো কর্মী নেই। | No active staff. |  |
| `staff.phoneTail` | ফোন …{tail} | phone …{tail} |  |
| `staff.suspended` | {name} স্থগিত। তাঁর চলমান সেশনও বন্ধ। | {name} is suspended, and any session of theirs has ended. |  |

## role

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `role.patient` | রোগী | Patient |  |
| `role.caregiver` | পরিচর্যাকারী | Caregiver |  |
| `role.doctor` | ডাক্তার | Doctor |  |
| `role.verifier` | যাচাইকারী | Verifier |  |
| `role.clinical_reviewer` | ক্লিনিক্যাল রিভিউয়ার | Clinical reviewer |  |
| `role.admin` | অ্যাডমিন | Admin |  |

## met

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `met.refresh` | আবার পড়ুন | Read again |  |
| `met.at` | পড়া হয়েছে {at} | Read {at} |  |
| `met.leaseAlert` | মেয়াদ পেরোনো লিজ: {n}টি। এক্সট্র্যাকশন ওয়ার্কার পরীক্ষা করুন। | Expired leases: {n} (D13 alert: more than 0). Check the extraction worker. |  |
| `met.documents` | অবস্থা অনুযায়ী নথি | Documents by status |  |
| `met.worker` | ওয়ার্কার | Worker |  |
| `met.due` | চালানোর অপেক্ষায় | Due |  |
| `met.in_flight` | চলছে | In progress |  |
| `met.lease_expired` | মেয়াদ পেরোনো লিজ | Expired leases |  |
| `met.waiting_backoff` | পরের চেষ্টার অপেক্ষায় | Waiting for the next try |  |
| `met.failed` | ব্যর্থ | Failed |  |
| `met.failed_retryable` | ব্যর্থ, আবার চেষ্টা করা যায় | Failed, can retry |  |
| `met.failed_permanent` | ব্যর্থ, স্থায়ী ত্রুটি | Failed, permanent error |  |
| `met.failed_budget_exhausted` | ব্যর্থ, সব চেষ্টা শেষ | Failed, all tries used |  |
| `met.failed_no_retry_last_hour` | গত এক ঘণ্টায় আর চেষ্টা নয় এমন ব্যর্থতা | No-retry failures in the last hour |  |
| `met.due_over_15_minutes` | পনেরো মিনিটের বেশি অপেক্ষায় | Waiting over 15 minutes |  |
| `met.attempts_open_runs` | চলমান চেষ্টা | Attempts in open runs |  |
| `met.ocr_executions_total` | মোট OCR চালানো | OCR runs in total |  |

## qr

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `qr.title` | রোগীকে এই QR স্ক্যান করতে বলুন | Ask the patient to scan this QR |  |
| `qr.note` | রোগী ফোনের ক্যামেরা দিয়ে স্ক্যান করে নিজের অ্যাপে অনুমতি দেবেন। এটি একবারই চলবে। | The patient scans it with their phone camera and approves in their own app. It works once. |  |
| `qr.left` | বাকি সময়: {time} | Time left: {time} |  |
| `qr.alt` | এই সম্মতি অনুরোধের QR কোড | QR code for this consent request |  |
| `qr.codeNote` | ফোনে স্ক্যান না হলে রোগী অ্যাপের সম্মতি পাতায় এই কোডটি লিখবেন: | If the phone can't scan, the patient types this code on the Consent page of their app: |  |
| `qr.waiting` | রোগীর উত্তরের অপেক্ষায়… | Waiting for the patient… |  |
| `qr.declined` | রোগী রাজি হননি। রেকর্ড খোলা হবে না। | The patient declined. The record stays closed. |  |
| `qr.expired` | QR-এর মেয়াদ শেষ। দরকার হলে নতুন অনুরোধ পাঠান। | The QR has expired. Send a new request if you still need it. |  |

## pqr

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `pqr.title` | ডাক্তারের অনুরোধ | Doctor's request |  |
| `pqr.asks` | {name} আপনার রেকর্ড দেখতে চান। | {name} wants to see your record. |  |
| `pqr.hours` | আপনি আগে বন্ধ না করলে প্রবেশ থাকবে {hours} ঘণ্টা। | Access lasts {hours} hours unless you stop it sooner. |  |
| `pqr.only` | শুধু তখনই অনুমতি দিন, যখন ডাক্তার আপনার সামনে আছেন এবং নামটি তাঁরই। | Allow only if the doctor is with you and this is their name. |  |
| `pqr.approved` | অনুমতি দেওয়া হয়েছে। সম্মতি পাতায় যেকোনো সময় বন্ধ করতে পারবেন। | Access allowed. You can stop it at any time on the Consent page. |  |
| `pqr.declined` | আপনি রাজি হননি। কিছুই শেয়ার হয়নি। | You declined. Nothing was shared. |  |
| `pqr.closed` | এই অনুরোধটি আর খোলা নেই। মেয়াদ শেষ হয়ে থাকতে পারে বা আগেই ব্যবহার হয়েছে। দরকার হলে ডাক্তারকে নতুন অনুরোধ পাঠাতে বলুন। | This request is no longer open. It may have expired or been used. Ask the doctor for a new one if needed. |  |
| `pqr.toConsent` | সম্মতি পাতায় যান | Go to Consent |  |
| `pqr.enterTitle` | ডাক্তারের QR অনুরোধ | A doctor's QR request |  |
| `pqr.code` | ডাক্তারের পর্দায় দেখানো কোড | Code shown on the doctor's screen |  |
| `pqr.codeHint` | QR স্ক্যান করতে না পারলে কোডটি এখানে লিখুন। | Type it here if you can't scan the QR. |  |
| `pqr.open` | অনুরোধ খুলুন | Open request |  |

## inbox

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `inbox.empty` | কোনো বিজ্ঞপ্তি নেই। | No notifications. |  |
| `inbox.new` | নতুন | New |  |
| `inbox.read` | পড়া হয়েছে | Mark as read |  |
| `inbox.consent` | {name} আপনার রেকর্ড দেখতে চেয়েছেন ({what})। আপনি কোড না বললে বা QR-এ অনুমতি না দিলে কিছুই শেয়ার হবে না। | {name} asked to see your record ({what}). Nothing is shared unless you tell them the code or approve their QR. |  |
| `inbox.caregiver` | {name} আপনার পরিচর্যাকারী হতে চান ({what})। | {name} asked to be your caregiver ({what}). |  |
| `inbox.consentGranted` | আপনার অনুমতিতে {name} এখন আপনার রেকর্ড দেখতে পারেন ({what})। | With your permission, {name} can now see your record ({what}). |  |
| `inbox.caregiverGranted` | আপনার অনুমতিতে {name} এখন আপনার পরিচর্যাকারী ({what})। | With your permission, {name} is now your caregiver ({what}). |  |
| `inbox.emergency` | জরুরি প্রবেশ: {name} {facility}-এ আপনার জরুরি কার্ড খুলেছেন। | Emergency access: {name} opened your emergency card at {facility}. |  |
| `inbox.security` | নিরাপত্তা বিজ্ঞপ্তি। এটি বন্ধ করা যায় না। | Security notice. It can't be switched off. |  |
| `inbox.answer` | সম্মতি পাতায় উত্তর দিন | Answer on the Consent page |  |
| `inbox.history` | প্রবেশের ইতিহাস দেখুন | See access history |  |

## th

| Key | Bangla | English (source meaning) | Review |
|---|---|---|---|
| `th.note` | ডিফল্ট মান আসে ক্লিনিক্যাল রিভিউয়ারের অনুমোদিত নিয়ম থেকে। আপনার পরিবর্তন শুধু এই রোগীর জন্য; প্রতিটি পরিবর্তন নতুন সংস্করণ, অডিটে লেখা থাকে। | Defaults come from the clinical reviewer's approved rules. Your change applies to this patient only; every change is a new, audited version. |  |
| `th.version` | সংস্করণ {v} | Version {v} |  |
| `th.changed` | সর্বশেষ পরিবর্তন: {name}, {date} | Last changed by {name}, {date} |  |
| `th.unchanged` | এখনো কোনো পরিবর্তন হয়নি। | No changes yet. |  |
| `th.default` | ডিফল্ট: {value} | Default: {value} |  |
| `th.defaultPending` | ডিফল্ট: রিভিউয়ার-অনুমোদন বাকি | Default: REVIEWER-PENDING |  |
| `th.override` | এই রোগীর জন্য সীমা ({unit}) | Limit for this patient ({unit}) |  |
| `th.hint` | খালি রাখলে ডিফল্ট চলবে। | Leave empty to use the default. |  |
| `th.bad` | একটি সংখ্যা লিখুন, অথবা ডিফল্টের জন্য খালি রাখুন। | Enter a number, or leave it empty for the default. |  |
| `th.save` | সীমা সংরক্ষণ করুন | Save thresholds |  |
| `th.saved` | সংরক্ষিত হয়েছে, সংস্করণ {v}। | Saved as version {v}. |  |
| `th.reload` | আবার লোড করুন | Reload |  |
| `th.noRules` | এখনো কোনো অনুমোদিত সীমার নিয়ম নেই। ক্লিনিক্যাল রিভিউয়ার নিয়ম অনুমোদন করলে এখানে ঘর দেখা যাবে। | No approved threshold rules yet. Fields appear here once the clinical reviewer approves a rule. |  |
