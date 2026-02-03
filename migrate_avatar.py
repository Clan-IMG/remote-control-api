"""
Migration script to add avatar_url column to users table
Run this script once to add the column.
"""
import asyncio
from sqlalchemy import text
from src.app.database import engine


async def migrate():
    print("Starting migration...")
    async with engine.begin() as conn:
        # Check if column already exists
        result = await conn.execute(text("""
            SELECT COUNT(*) 
            FROM information_schema.COLUMNS 
            WHERE TABLE_NAME = 'users' 
            AND COLUMN_NAME = 'avatar_url'
        """))
        exists = result.scalar()
        
        if exists:
            print("Column 'avatar_url' already exists. Skipping.")
        else:
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN avatar_url VARCHAR(500) NULL AFTER username"
            ))
            print("Column 'avatar_url' added successfully!")
    
    print("Migration complete!")


if __name__ == "__main__":
    asyncio.run(migrate())
