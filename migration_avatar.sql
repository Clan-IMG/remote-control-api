-- Migration: Add avatar_url column to users table
-- Run this SQL in your database

-- Check if column exists first (for safety)
SET @dbname = DATABASE();
SET @tablename = 'users';
SET @columnname = 'avatar_url';

SET @exists = (
    SELECT COUNT(*) 
    FROM information_schema.COLUMNS 
    WHERE TABLE_SCHEMA = @dbname 
    AND TABLE_NAME = @tablename 
    AND COLUMN_NAME = @columnname
);

-- Only add if it doesn't exist
SET @query = IF(@exists = 0,
    'ALTER TABLE users ADD COLUMN avatar_url VARCHAR(500) NULL AFTER username',
    'SELECT "Column avatar_url already exists" AS message'
);

PREPARE stmt FROM @query;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
