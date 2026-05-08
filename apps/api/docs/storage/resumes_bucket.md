# Resumes Storage Bucket

## Overview

Student resumes are stored in a **private** Supabase Storage bucket named `resumes`.

- Files are never publicly accessible by URL.
- The backend obtains short-lived signed URLs when it needs to read a file for parsing.
- Students may upload only into their own folder.
- The parser service uses the service-role key to read files and write derived artifacts.

---

## Creating the Bucket

1. Open the Supabase dashboard → **Storage**.
2. Click **New bucket**.
3. Set:
   - **Name:** `resumes`
   - **Public bucket:** OFF (private)
   - **File size limit:** 10 MB (10485760 bytes)
   - **Allowed MIME types:** `application/pdf, application/vnd.openxmlformats-officedocument.wordprocessingml.document`
4. Click **Create bucket**.

---

## Path Convention

All objects follow this convention:

```
{user_id}/{resume_id}/original.{ext}
{user_id}/{resume_id}/normalized.txt     ← parser output (plain text)
{user_id}/{resume_id}/preview.pdf        ← future: rendered preview
```

The path is stored in `resumes.storage_path` and `resumes.storage_bucket` in the database.

---

## Storage RLS Policies

Run the following SQL in the Supabase SQL editor **after** creating the bucket.

```sql
-- ── Storage RLS for the 'resumes' bucket ──────────────────────

-- Students can read their own files (first path segment = their user_id).
create policy "resumes bucket: authenticated user read own"
  on storage.objects for select
  to authenticated
  using (
    bucket_id = 'resumes'
    and (storage.foldername(name))[1] = (select auth.uid()::text)
  );

-- Students can upload into their own folder only.
create policy "resumes bucket: authenticated user insert own"
  on storage.objects for insert
  to authenticated
  with check (
    bucket_id = 'resumes'
    and (storage.foldername(name))[1] = (select auth.uid()::text)
  );

-- Students can delete their own files.
create policy "resumes bucket: authenticated user delete own"
  on storage.objects for delete
  to authenticated
  using (
    bucket_id = 'resumes'
    and (storage.foldername(name))[1] = (select auth.uid()::text)
  );
```

> **Note:** The service-role key bypasses Storage RLS, so the parser
> service can read and write files without additional policies.

---

## Signed URL Pattern (Server-Side)

The backend must never expose the raw storage path as a public URL.
Instead, generate a short-lived signed URL when needed:

```python
# Server-side only — uses service-role key
client = get_supabase_client()
signed = client.storage.from_("resumes").create_signed_url(
    path=resume.storage_path,
    expires_in=300,  # 5 minutes
)
url = signed["signedURL"]
```

Pass the signed URL to the parser service, not to the browser.

---

## MVP File Limits

| Setting              | Value                                       |
|----------------------|---------------------------------------------|
| Max file size        | 10 MB                                       |
| Allowed types        | `application/pdf`, `.docx`                  |
| Retention            | Indefinite for MVP; add policy later        |
| Derived artifacts    | Stored in the same `{user_id}/{resume_id}/` folder |

---

## Future Considerations

- Add a DOCX→PDF normalisation step before parsing.
- Store parsed plain text in `{user_id}/{resume_id}/normalized.txt` and reference it from `parsed_resume_data.raw_text`.
- Add a virus/malware scan step between upload and parse job creation.
- Set object expiry or lifecycle rules once retention requirements are defined.
- Generate a PDF preview for in-app display without downloading the original.
