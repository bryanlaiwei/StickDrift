"""Live lobby sessions: streamed in from the resident's tab, watched by caregivers, saved and scored.

session.py  a session's state and its storage in Tiger Data (the ingest path)
visit.py    ending a visit: saving it to the resident's history, scoring it, its hand replay
watch.py    what caregivers read: briefs, full state and samples
stream.py   the caregiver WebSocket, fed by Postgres LISTEN/NOTIFY
routes.py   the HTTP routes
"""
