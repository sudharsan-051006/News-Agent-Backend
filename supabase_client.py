import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()  # 👈 loads .env file

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = (
    os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    or os.getenv("SUPABASE_KEY")
    or os.getenv("SUPABASE_ANON_KEY")
)

if supabase_url and supabase_key:
    try:
        supabase = create_client(supabase_url, supabase_key)
    except Exception as exc:
        print(f"⚠️ Warning: Could not initialize Supabase client: {exc}")
        class _FailedClient:
            def __getattr__(self, name):
                raise RuntimeError(f"Supabase client failed to initialize: {exc}")
        supabase = _FailedClient()
else:
    class _UninitializedClient:
        def __getattr__(self, name):
            raise RuntimeError(
                "Supabase client not initialized: Neither SUPABASE_SERVICE_ROLE_KEY nor SUPABASE_KEY is set in environment. "
                "Please configure these secrets in GitHub Actions or in your local .env file."
            )
    supabase = _UninitializedClient()
