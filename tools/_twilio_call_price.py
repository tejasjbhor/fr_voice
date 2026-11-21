"""Fetch Twilio price for Rohit call SID."""
import os
from dotenv import load_dotenv

load_dotenv(override=True)
from twilio.rest import Client

SID = "CA06d12321faefa2d68c5a7c968de01a5c"
c = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
call = c.calls(SID).fetch()
print("sid", call.sid)
print("duration_sec", call.duration)
print("price", call.price)
print("price_unit", call.price_unit)
print("status", call.status)
print("to", call.to)
print("direction", call.direction)
