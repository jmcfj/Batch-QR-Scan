"""Recognize web destinations without executing arbitrary URI schemes."""
from urllib.parse import urlsplit


def web_url(text):
    value = text.strip()
    if value.lower().startswith('www.'):
        value = 'https://' + value
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in ('http', 'https') or not parts.hostname:
            return None
        if parts.username is not None or parts.password is not None:
            return None
        _ = parts.port
    except ValueError:
        return None
    return value
