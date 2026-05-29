-- Migration 036: Recruiter session tokens
-- Provides server-issued, hashed session tokens for recruiter private-data endpoints.
-- Tokens are cryptographically random and stored only as SHA-256 hashes.

CREATE TABLE IF NOT EXISTS recruiter_session_tokens (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    requester_email TEXT        NOT NULL,
    token_hash      TEXT        NOT NULL UNIQUE,
    expires_at      TIMESTAMPTZ,
    revoked_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS recruiter_session_tokens_email_idx
    ON recruiter_session_tokens (requester_email);

-- Only the service role can read/write session tokens.
-- No client-side RLS policies; all access goes through the API layer.
ALTER TABLE recruiter_session_tokens ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all" ON recruiter_session_tokens
    FOR ALL TO service_role USING (true) WITH CHECK (true);
