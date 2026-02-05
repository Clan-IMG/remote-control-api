"""
Migration script to add indexes to generations table.
Run this inside the Docker container.
"""
import asyncio
import aiomysql
import os

DATABASE_URL = os.getenv("DATABASE_URL", "mysql+aiomysql://root:password@localhost:3306/pixelkid")

# Parse DATABASE_URL
def parse_db_url(url: str):
    # mysql+aiomysql://user:pass@host:port/db
    url = url.replace("mysql+aiomysql://", "")
    user_pass, rest = url.split("@")
    user, password = user_pass.split(":")
    host_port, db = rest.split("/")
    if ":" in host_port:
        host, port = host_port.split(":")
        port = int(port)
    else:
        host = host_port
        port = 3306
    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "db": db
    }

# --- Add reference image columns migration ---
REFERENCE_IMAGE_MIGRATION = (
    "reference_image_columns",
    "ALTER TABLE generations "
    "ADD COLUMN reference_image_url VARCHAR(500) NULL AFTER is_public, "
    "ADD COLUMN reference_strength FLOAT NULL DEFAULT 0.5 AFTER reference_image_url;"
)

INDEXES = [
    ("idx_generations_user_id", "CREATE INDEX idx_generations_user_id ON generations(user_id)"),
    ("idx_generations_created_at", "CREATE INDEX idx_generations_created_at ON generations(created_at)"),
    ("idx_generations_status", "CREATE INDEX idx_generations_status ON generations(status)"),
    ("idx_generations_is_public", "CREATE INDEX idx_generations_is_public ON generations(is_public)"),
    ("idx_generations_user_created", "CREATE INDEX idx_generations_user_created ON generations(user_id, created_at)"),
]

async def main():
    config = parse_db_url(DATABASE_URL)
    print(f"Connecting to database: {config['host']}:{config['port']}/{config['db']}")
    
    conn = await aiomysql.connect(
        host=config["host"],
        port=config["port"],
        user=config["user"],
        password=config["password"],
        db=config["db"]
    )
    
    async with conn.cursor() as cursor:
        # --- Run migrations ---
        for mig_name, mig_sql in MIGRATIONS:
            try:
                print(f"Applying migration: {mig_name}")
                await cursor.execute(mig_sql)
                await conn.commit()
                print(f"✓ Migration '{mig_name}' applied")
            except Exception as e:
                if "Duplicate column name" in str(e) or "already exists" in str(e):
                    print(f"✓ Migration '{mig_name}' already applied")
                else:
                    print(f"✗ Failed migration '{mig_name}': {e}")
        # Check existing indexes
        await cursor.execute("SHOW INDEX FROM generations")
        existing = await cursor.fetchall()
        existing_names = {row[2] for row in existing}  # Key_name is at index 2
        
        print(f"Existing indexes: {existing_names}")
        
        for index_name, create_sql in INDEXES:
            if index_name in existing_names:
                print(f"✓ Index '{index_name}' already exists")
            else:
                try:
                    await cursor.execute(create_sql)
                    await conn.commit()
                    print(f"✓ Created index '{index_name}'")
                except Exception as e:
                    print(f"✗ Failed to create index '{index_name}': {e}")
    
    conn.close()
    print("\nMigration complete!")

if __name__ == "__main__":
    asyncio.run(main())
