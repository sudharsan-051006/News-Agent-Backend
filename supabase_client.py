import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()  # 👈 loads .env file

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_ROLE_KEY")
)
