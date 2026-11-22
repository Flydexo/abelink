-- Abelink initial PostgreSQL + pgvector schema

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name TEXT NOT NULL,
    email TEXT,
    linkedin_url TEXT UNIQUE,
    photo_url TEXT,
    promo_year INT,
    "current_role" TEXT,
    current_company TEXT,
    sector TEXT,
    location TEXT,
    bio TEXT,
    experiences JSONB NOT NULL DEFAULT '[]'::jsonb,
    education JSONB NOT NULL DEFAULT '[]'::jsonb,
    associations TEXT[] NOT NULL DEFAULT '{}',
    passions TEXT[] NOT NULL DEFAULT '{}',
    is_student BOOLEAN NOT NULL DEFAULT FALSE,
    has_imported_linkedin BOOLEAN NOT NULL DEFAULT FALSE,
    enrichment_source TEXT NOT NULL DEFAULT 'BASE_DB',
    last_enriched_at TIMESTAMPTZ,
    embedding VECTOR(768),
    search_tsv tsvector GENERATED ALWAYS AS (
        to_tsvector(
            'french',
            coalesce(full_name, '') || ' ' ||
            coalesce("current_role", '') || ' ' ||
            coalesce(current_company, '') || ' ' ||
            coalesce(sector, '') || ' ' ||
            coalesce(bio, '')
        )
    ) STORED,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    target_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    edge_type TEXT NOT NULL,
    probability DOUBLE PRECISION NOT NULL CHECK (probability >= 0.05 AND probability <= 0.99),
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_id, target_id, edge_type)
);

CREATE TABLE IF NOT EXISTS api_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL DEFAULT 'default',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ
);

-- Indexes for hybrid semantic + lexical + graph retrieval
CREATE INDEX IF NOT EXISTS idx_profiles_embedding_hnsw
    ON profiles USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_profiles_search_tsv
    ON profiles USING gin (search_tsv);

CREATE INDEX IF NOT EXISTS idx_profiles_associations_gin
    ON profiles USING gin (associations);

CREATE INDEX IF NOT EXISTS idx_profiles_passions_gin
    ON profiles USING gin (passions);

CREATE INDEX IF NOT EXISTS idx_profiles_email
    ON profiles (lower(email));

CREATE INDEX IF NOT EXISTS idx_profiles_is_student
    ON profiles (is_student);

CREATE INDEX IF NOT EXISTS idx_edges_source_id
    ON edges (source_id);

CREATE INDEX IF NOT EXISTS idx_edges_target_id
    ON edges (target_id);

CREATE INDEX IF NOT EXISTS idx_api_tokens_profile_id
    ON api_tokens (profile_id);
