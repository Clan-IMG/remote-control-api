import asyncio
from sqlalchemy import text
from src.app.database import engine

async def migrate():
    print("Starting enum migration...")
    async with engine.begin() as conn:
        print("Modifying generations table...")
        # Update the ENUM definition to include new agent types
        # Using the UPPERCASE names as seen in the SQLAlchemy bindings/logs
        await conn.execute(text("""
            ALTER TABLE generations MODIFY COLUMN model 
            ENUM('BLOCK_AGENT', 'ITEM_AGENT', 'ARMOR_AGENT', 'PROMPT_AGENT', 'PICTURE_AGENT', 'LOGO_AGENT_2D', 'LOGO_AGENT_3D') 
            NOT NULL
        """))
        print("Enum values updated successfully!")
    
    print("Migration complete!")

if __name__ == "__main__":
    asyncio.run(migrate())
