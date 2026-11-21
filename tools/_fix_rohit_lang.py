from core.database import upsert_demo_user, get_user_by_phone
u = upsert_demo_user(name="Rohit", phone="+917020773368", language="hi-IN")
print("updated", u and u.get("language"), u and u.get("name"))
print("verify", get_user_by_phone("+917020773368"))
