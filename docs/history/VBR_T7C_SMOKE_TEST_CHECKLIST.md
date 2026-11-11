# VeriBridge AI — T7C VBR Public Report Smoke Test Checklist

Status: Manual QA checklist
Scope: Mythos MVP / Verified Build Report only
Branch: wip/recruiter-evidence-quality-cleanup

## Goal

Verify the full VBR report loop works safely:

1. Private report draft exists
2. Report can be submitted for review
3. Report can be published
4. Public token is created only at publish time
5. Public backend endpoint loads the report
6. Public frontend route `/r/[token]` renders the report
7. No private fields leak publicly

## Backend targeted tests

Run:

    pytest apps/api/tests/test_vbr_report_draft.py apps/api/tests/test_vbr_report_publish.py apps/api/tests/test_vbr_public_report.py -q

Expected:

- All tests pass
- Only FastAPI `on_event` deprecation warnings are acceptable

## Public report safety checks

The public API response must NOT include:

- public_token
- storage_path
- storagePath
- media_storage_path
- signed_url
- signedUrl
- local temp paths like /tmp/
- Supabase storage object URLs
- full transcript text
- raw metadata
- private user email
- service/internal secrets

## Frontend route checks

Route:

    /r/[token]

Expected page behavior:

- No login required
- Shows Verified Build Report label
- Shows project title
- Shows published date when available
- Shows summary
- Shows claim judgments
- Shows evidence count / safe evidence labels only
- Shows methodology and verification note
- Does not display public token
- Does not display storage paths, signed URLs, local paths, raw metadata, or full transcript text
- Shows unavailable state for invalid/unpublished token

## API route checks

Public endpoint:

    GET /api/v1/public/vbr/reports/{public_token}

Expected behavior:

- Published report with token: 200
- Unknown token: 404
- Unpublished report: 404
- Cleared token: 404
- Unsafe body: 404
- No auth dependency required

## Final MVP report-loop definition

The report loop is considered complete when this flow works:

    draft-report
    -> submit-report-review
    -> publish-report
    -> public API by token
    -> public /r/[token] page
