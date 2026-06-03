import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")

# 👇 ADD THESE 2 LINES
print("SUPABASE_URL =", repr(url))
print("SUPABASE_KEY exists =", bool(key))
supabase = create_client(url, key)
