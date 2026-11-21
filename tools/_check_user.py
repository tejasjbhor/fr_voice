import os
from dotenv import load_dotenv
load_dotenv(override=True)
print("PRODUCT", os.getenv("PRODUCT"))
print("SERVER_PUBLIC_URL", os.getenv("SERVER_PUBLIC_URL"))
print("USER_LANGUAGE", os.getenv("USER_LANGUAGE"))

from core.database import get_user_by_phone, normalize_phone
for raw in ("+917020773368", "+33699955835"):
    u = get_user_by_phone(raw)
    print(raw, "->", None if not u else {
        "id": u.get("id"), "name": u.get("name"),
        "language": u.get("language"), "role": u.get("account_role"),
    })
