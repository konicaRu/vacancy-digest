# LinkedIn hashtags integration

> Execution: executing-plans, inline; TDD and final independent review.

**Goal:** Enable bounded authenticated browser search in the existing scheduled digest on 20 November, no LLM or paid API.
**Spec:** docs/linkedin_posts_plan_addendum_2026-11-19.md and user-approved remote rule.
**Architecture:** Existing isolated Chrome controller supplies expanded public post cards to an IPC client/SourceResult adapter. No cookies export; existing SQLite transaction commits only after successful SMTP. Source failure is isolated.

## Tasks
- [x] Pilot: inspect observed DOM, extract full text and stable post IDs, verify #hiring/#ProductAnalyst/#AnalyticsJobs independently; casefold query dedup.
- [x] RED/GREEN: pure normalization, multivacancy posts, Russian body/role/grade/remote/closed guards; existing classifier retained for other sources.
- [x] RED/GREEN: IPC/collector bounded timeouts, partial results, seen IDs and per-tag metrics; autostart isolated browser with existing profile.
- [x] RED/GREEN: permanent suppression of confirmed employer ID/URL or exact publication, not weak semantic matches; old code/status preserved.
- [x] RED/GREEN: collect_all/digest stats/config, dry-run/SMTP failure/empty transaction integration.
- [x] Final: independent review, full suite, live scan and pipeline on copy of SQLite with mail disabled, verify scheduler and enable config only after successful pilot.

## Review focus
Login/challenge cannot look like empty results; partial text cannot pass as full; post IDs stable across tags and reposts; different teams/grades/IDs never merged weakly; incomplete tags retry without advancing their bookmark; browser IPC collision fails safely; source failure does not stop other sources. No system CA changes, no paid search, no automated auth.

## Decisions / progress
- User authorizes implementation from the supplied addendum and activation for tomorrow. No additional design approval needed.
- Existing runtime/browser profile reused. Production source enabled with start_date 2026-11-20 after live validation.
- Final verification: 291 tests passed; live copy dry-run selected one real vacancy, SMTP=0, business state unchanged.
