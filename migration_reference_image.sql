
ALTER TABLE generations
ADD COLUMN reference_image_url VARCHAR(500) NULL AFTER is_public,
ADD COLUMN reference_strength FLOAT NULL DEFAULT 0.5 AFTER reference_image_url;
