#!/usr/bin/env python3
import os
from dotenv import load_dotenv
import psycopg2

# Carga explícita de .env junto a este script
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

dsn = os.getenv("DATABASE_URL")
print("🔑 DSN usado:", repr(dsn))

try:
    conn = psycopg2.connect(dsn)
    print("✅ Conexión Postgres OK")
    conn.close()
except Exception as e:
    print("❌ Error de conexión:", type(e).__name__, str(e))
