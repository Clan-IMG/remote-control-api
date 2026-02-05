import asyncio
from sqlalchemy import text
from src.app.database import engine

async def migrate():
    print("Starting user auth migration...")
    async with engine.begin() as conn:
        print("Checking/Adding login_enabled column...")
        try:
            await conn.execute(text("ALTER TABLE users ADD COLUMN login_enabled BOOLEAN DEFAULT FALSE"))
            print("Added login_enabled")
        except Exception as e:
            print(f"login_enabled might already exist (ignoring error): {e}")

        print("Checking/Adding is_admin column...")
        try:
            await conn.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT FALSE"))
            print("Added is_admin")
        except Exception as e:
            print(f"is_admin might already exist (ignoring error): {e}")
            
        print("Creating system_settings table if not exists...")
        try:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS system_settings (
                    `key` VARCHAR(50) PRIMARY KEY,
                    `value` VARCHAR(255),
                    `is_boolean` BOOLEAN DEFAULT FALSE,
                    `description` VARCHAR(255),
                    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                )
            """))
            print("System settings table checked/created.")
        except Exception as e:
            print(f"Error creating system_settings: {e}")
        
        # Set first user as admin
        print("Setting first user as admin...")
        try:
            await conn.execute(text("UPDATE users SET is_admin=1, login_enabled=1 ORDER BY created_at ASC LIMIT 1"))
            print("First user promoted to admin.")
        except Exception as e:
            print(f"Could not promote first user: {e}")

    print("Migration complete!")

if __name__ == "__main__":
    asyncio.run(migrate())
