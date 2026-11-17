"""The writers, by platform."""
from __future__ import annotations

from . import email, linkedin, messenger, outlook, sms, telegram, whatsapp

MODULES = {
    "email": email,
    "telegram": telegram,
    "whatsapp": whatsapp,
    "messenger": messenger,
    "linkedin": linkedin,
    "sms": sms,
    "outlook": outlook,
}
