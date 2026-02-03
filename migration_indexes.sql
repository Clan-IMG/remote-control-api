-- Migration: Add indexes to generations table for better query performance
-- Run this in your MySQL database

-- Index on user_id for filtering by user
CREATE INDEX IF NOT EXISTS idx_generations_user_id ON generations(user_id);

-- Index on created_at for ordering
CREATE INDEX IF NOT EXISTS idx_generations_created_at ON generations(created_at);

-- Index on status for filtering
CREATE INDEX IF NOT EXISTS idx_generations_status ON generations(status);

-- Index on is_public for gallery queries
CREATE INDEX IF NOT EXISTS idx_generations_is_public ON generations(is_public);

-- Composite index for user + created_at (most common query pattern)
CREATE INDEX IF NOT EXISTS idx_generations_user_created ON generations(user_id, created_at);

-- Show all indexes on generations table
SHOW INDEX FROM generations;
