# Google Apps Script migration

This folder ports the current meal and weekend Psalm notification flow to a standalone Google Apps Script project. It is a test implementation; the existing GitHub Actions workflow remains active until you deliberately switch over.

## What it does

- Weekdays: query NEIS for **today's** menu, then send the lunch and eligible Tuesday/Thursday dinner messages to each configured Kakao account's own chat.
- Weekends: send the existing 55-week Psalm schedule, starting Saturday, 2026-10-17.
- Weekends and South Korean public holidays: skip meal notifications. The project reads the Korean holiday calendar configured in Script Properties or uses Google's South Korea holiday calendar ID by default.
- If Kakao rotates a refresh token, save the replacement immediately in Script Properties.
- `DRY_RUN=true` queries NEIS and logs message previews without requesting Kakao tokens or sending messages.

## Create and configure the Apps Script project

1. Create a standalone project at [script.google.com](https://script.google.com/).
2. Copy `Code.gs` into the editor. In **Project Settings**, enable **Show `appsscript.json` manifest file** and copy the manifest from this folder.
3. Set the project time zone to `Asia/Seoul` (also specified in the manifest).
4. Under **Project Settings → Script Properties**, add the required values below. Keep the project private and grant editor access only to people who may handle these credentials.

| Property | Value |
| --- | --- |
| `NEIS_API_KEY` | NEIS API key |
| `OFFICE_CODE` | School education office code |
| `SCHOOL_CODE` | School code |
| `KAKAO_REST_API_KEY` | Kakao app REST API key used to issue the family tokens |
| `KAKAO_CLIENT_SECRET` | Kakao Client Secret if enabled; otherwise omit |
| `KAKAO_REFRESH_TOKEN_ME` | Owner's Kakao refresh token |
| `KAKAO_REFRESH_TOKEN_WIFE` | Spouse's Kakao refresh token |
| `KAKAO_REFRESH_TOKEN_DAUGHTER` | Daughter's Kakao refresh token |
| `DRY_RUN` | Optional: set to `true` to suppress Kakao sends |
| `KOREAN_HOLIDAY_CALENDAR_ID` | Optional override for the Korean holiday calendar ID |

Set only the recipient token properties you need. Tokens are held in Script Properties and are not included in this repository. The legacy `KAKAO_REFRESH_TOKENS` JSON array property is also supported.

## Test before switching

1. Set `DRY_RUN` to `true`.
2. From the editor, run `previewMealNow`. Authorize the requested NEIS fetch permission, then inspect **Executions** for today's menu.
3. Run `runMealNow`. With dry-run enabled it will apply the same date, holiday, meal-filtering, and formatting rules and log Kakao message previews without sending.
4. When ready to verify delivery, remove `DRY_RUN` (or set it to `false`), configure only your own Kakao refresh token first, and run `runMealNow` manually. It sends a real Kakao message.
5. Once manual sending is confirmed, run `installTriggers` and authorize the trigger and calendar access. It creates weekday meal triggers near 06:25 and weekend Psalm triggers near 09:00 KST. Running it again replaces only these handlers' triggers.
6. Check Apps Script **Executions** for results. Add other family token properties only after the owner account works.

Apps Script time triggers are approximate: `nearMinute(25)` allows a 15-minute range, and Google may choose a consistent minute within that range. The trigger cannot promise exact delivery time.

## Switch from GitHub Actions

Keep GitHub Actions active while testing with `DRY_RUN=true`. For a real Kakao delivery test, pause or disable the GitHub scheduled workflow first to avoid sending duplicate messages that morning. After Apps Script triggers are installed and a real run succeeds, disable the GitHub workflow's schedule (you can retain `workflow_dispatch` for manual fallback). Do not run both real schedules at the same time.

Google Apps Script quotas and Kakao/NEIS API availability still apply. A trigger failure is visible in Apps Script **Executions** and may generate an email from Google to the account that owns the trigger.
