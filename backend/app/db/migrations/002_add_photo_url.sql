-- Add LinkedIn profile picture URL column to existing profiles tables
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS photo_url TEXT;
