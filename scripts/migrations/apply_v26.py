import asyncio
import os
import sys

# Ensure app is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.database import engine

async def main():
    migration_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "supabase", "migration_v26_operation_progress_trigger.sql"))
    
    print(f"Reading migration file: {migration_file}")
    with open(migration_file, "r", encoding="utf-8") as f:
        sql_content = f.read()

    print("Connecting to the database...")
    async with engine.begin() as conn:
        raw_conn = await conn.get_raw_connection()
        print(f"raw_conn type: {type(raw_conn)}")
        
        driver_conn = None
        if hasattr(raw_conn, "driver_connection"):
            driver_conn = raw_conn.driver_connection
        elif hasattr(raw_conn, "dbapi_connection") and hasattr(raw_conn.dbapi_connection, "driver_connection"):
            driver_conn = raw_conn.dbapi_connection.driver_connection
        
        if driver_conn is not None:
            print(f"driver_conn type: {type(driver_conn)}")
            await driver_conn.execute(sql_content)
            print("OK: Migration applied successfully via driver_connection!")
        else:
            print("driver_conn not found, trying raw_conn.execute...")
            await raw_conn.execute(sql_content)
            print("OK: Migration applied successfully via raw_conn!")

if __name__ == "__main__":
    asyncio.run(main())
