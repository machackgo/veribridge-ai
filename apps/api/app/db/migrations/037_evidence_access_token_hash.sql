-- Migration 037: Hash evidence access tokens at rest
-- Adds an access_token_hash column to evidence_access_grants so that
-- plaintext bearer tokens are never stored in the database.
-- Existing rows are back-filled with sha256(access_token) so existing
-- recruiter access links continue to work.

ALTER TABLE evidence_access_grants
    ADD COLUMN IF NOT EXISTS access_token_hash TEXT;

-- Back-fill: hash every existing plaintext token using built-in sha256().
-- sha256() is available in PostgreSQL 11+ (Supabase uses PG 15+).
UPDATE evidence_access_grants
    SET access_token_hash = encode(sha256(access_token::bytea), 'hex')
    WHERE access_token IS NOT NULL
      AND access_token_hash IS NULL;

-- Unique index on the hash for fast O(1) token lookup.
CREATE UNIQUE INDEX IF NOT EXISTS evidence_access_grants_token_hash_idx
    ON evidence_access_grants (access_token_hash)
    WHERE access_token_hash IS NOT NULL;

-- After back-fill, new grants will store only access_token_hash and
-- leave access_token NULL.  The service layer supports both columns
-- so existing rows with only access_token continue to work.
