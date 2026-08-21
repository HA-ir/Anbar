"""Bot API storage backend (F2). Placeholder for F1: interface only."""


class BotBackendNotImplemented(Exception):
    pass


# F2 will provide:
# - httpx-based sendDocument / getFile (no bot framework)
# - private channel as storage (bot = admin, zero members)
# - file_id captured from the message, never deleted