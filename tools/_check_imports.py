import sys
print("python", sys.version)
mods = ["colorama", "fastapi", "uvicorn", "dotenv", "aiohttp", "sqlalchemy", "requests"]
for m in mods:
    try:
        __import__(m)
        print("OK", m)
    except Exception as e:
        print("MISSING", m, e)
