"""Two-role auth: seniors (players) and caregivers (viewers).

Seniors are rows in `participants` with a username + password. Caregivers are
rows in `caregivers`. A login cookie (HttpOnly) maps to an `auth_sessions` row.
"""
import hashlib
import os
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from typing import Literal, Optional
from uuid import UUID

import psycopg
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from starlette.requests import HTTPConnection
from pydantic import BaseModel, Field

from .db import pool

router = APIRouter(tags=["auth"])

COOKIE_NAME = "sd_session"
SESSION_HOURS = 12
USERNAME_RE = re.compile(r"^[A-Za-z0-9 _-]{3,24}$")

hasher = PasswordHasher()
# Verified against for unknown users so a failed login takes the same time
# whether or not the username exists.
_DUMMY_HASH = hasher.hash(secrets.token_hex(16))

Role = Literal["senior", "caregiver"]


# ---- models --------------------------------------------------------------

class SeniorSignup(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=128)
    dominant_hand: Literal["left", "right", "unknown"] = "unknown"


class CaregiverSignup(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=128)
    display_name: str = Field(default="", max_length=40)
    invite_code: str = Field(max_length=128)


class Login(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=128)


class Me(BaseModel):
    role: Role
    account_id: UUID
    username: str
    display_name: str
    dominant_hand: Optional[str] = None


# ---- helpers -------------------------------------------------------------

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _normalize_username(raw: str) -> str:
    return " ".join(raw.split())


def _start_session(conn, role: Role, account_id, response: Response) -> None:
    token = secrets.token_urlsafe(32)
    conn.execute("DELETE FROM auth_sessions WHERE expires_at < now()")
    conn.execute(
        """INSERT INTO auth_sessions (token_hash, role, account_id, expires_at)
           VALUES (%s, %s, %s, now() + make_interval(hours => %s))""",
        (_token_hash(token), role, account_id, SESSION_HOURS),
    )
    response.set_cookie(
        COOKIE_NAME, token, max_age=SESSION_HOURS * 3600,
        httponly=True, samesite="lax", path="/",
    )


def _lookup(request: HTTPConnection) -> Optional[dict]:
    """The signed-in account for a request or a WebSocket (both carry the login cookie)."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    with pool.connection() as conn:
        sess = conn.execute(
            "SELECT role, account_id FROM auth_sessions WHERE token_hash = %s AND expires_at > now()",
            (_token_hash(token),),
        ).fetchone()
        if sess is None:
            return None
        if sess["role"] == "senior":
            row = conn.execute(
                "SELECT participant_id AS account_id, username, alias, dominant_hand "
                "FROM participants WHERE participant_id = %s AND username IS NOT NULL",
                (sess["account_id"],),
            ).fetchone()
            if row is None:
                return None
            return {"role": "senior", "account_id": row["account_id"], "username": row["username"],
                    "display_name": row["alias"], "dominant_hand": row["dominant_hand"]}
        row = conn.execute(
            "SELECT caregiver_id AS account_id, username, display_name FROM caregivers WHERE caregiver_id = %s",
            (sess["account_id"],),
        ).fetchone()
        if row is None:
            return None
        return {"role": "caregiver", "account_id": row["account_id"], "username": row["username"],
                "display_name": row["display_name"], "dominant_hand": None}


lookup = _lookup


def current_account(request: Request) -> dict:
    account = _lookup(request)
    if account is None:
        raise HTTPException(401, "Not logged in.")
    return account


def current_senior(request: Request) -> dict:
    account = current_account(request)
    if account["role"] != "senior":
        raise HTTPException(403, "This area is for residents.")
    return account


def current_caregiver(request: Request) -> dict:
    account = current_account(request)
    if account["role"] != "caregiver":
        raise HTTPException(403, "This area is for care team members.")
    return account


# ---- senior auth ---------------------------------------------------------

@router.post("/auth/senior/signup", response_model=Me, status_code=201)
def senior_signup(body: SeniorSignup, response: Response):
    username = _normalize_username(body.username)
    if not USERNAME_RE.match(username):
        raise HTTPException(422, "Usernames are 3–24 letters, numbers, spaces, - or _.")
    if len(body.password) < 8:
        raise HTTPException(422, "Passwords need at least 8 characters.")
    try:
        with pool.connection() as conn:
            row = conn.execute(
                """INSERT INTO participants (alias, dominant_hand, username, password_hash)
                   VALUES (%s, %s, %s, %s)
                   RETURNING participant_id, alias, dominant_hand, username""",
                (username, body.dominant_hand, username, hasher.hash(body.password)),
            ).fetchone()
            _start_session(conn, "senior", row["participant_id"], response)
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "That username is taken. Try another.")
    return {"role": "senior", "account_id": row["participant_id"], "username": row["username"],
            "display_name": row["alias"], "dominant_hand": row["dominant_hand"]}


@router.post("/auth/senior/login", response_model=Me)
def senior_login(body: Login, response: Response):
    username = _normalize_username(body.username)
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT participant_id, alias, dominant_hand, username, password_hash "
            "FROM participants WHERE lower(username) = lower(%s)",
            (username,),
        ).fetchone()
        try:
            hasher.verify(row["password_hash"] if row else _DUMMY_HASH, body.password)
        except VerificationError:
            row = None
        if row is None:
            raise HTTPException(401, "Username or password is incorrect.")
        _start_session(conn, "senior", row["participant_id"], response)
    return {"role": "senior", "account_id": row["participant_id"], "username": row["username"],
            "display_name": row["alias"], "dominant_hand": row["dominant_hand"]}


# ---- caregiver auth ------------------------------------------------------

@router.post("/auth/caregiver/login", response_model=Me)
def caregiver_login(body: Login, response: Response):
    username = _normalize_username(body.username)
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT caregiver_id, username, display_name, password_hash "
            "FROM caregivers WHERE lower(username) = lower(%s)",
            (username,),
        ).fetchone()
        try:
            hasher.verify(row["password_hash"] if row else _DUMMY_HASH, body.password)
        except VerificationError:
            row = None
        if row is None:
            raise HTTPException(401, "Username or password is incorrect.")
        _start_session(conn, "caregiver", row["caregiver_id"], response)
    return {"role": "caregiver", "account_id": row["caregiver_id"], "username": row["username"],
            "display_name": row["display_name"], "dominant_hand": None}


# Caregivers can read every resident's results, so registering needs a care-team
# access code from CAREGIVER_INVITE_CODE in backend/.env. With no code set,
# registration is off. Wrong codes are rate limited per client address.
_FAIL_WINDOW_S = 15 * 60
_FAIL_LIMIT = 8
_failures: dict = defaultdict(deque)
_failures_lock = threading.Lock()


def _check_invite(request: Request, code: str) -> None:
    expected = os.environ.get("CAREGIVER_INVITE_CODE", "").strip()
    if not expected:
        raise HTTPException(403, "Care team registration is turned off. Ask the person who runs Stick Drift "
                                 "to set an access code.")
    who = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _failures_lock:
        recent = _failures[who]
        while recent and now - recent[0] > _FAIL_WINDOW_S:
            recent.popleft()
        if len(recent) >= _FAIL_LIMIT:
            raise HTTPException(429, "Too many wrong access codes. Please wait 15 minutes and try again.")
        if not secrets.compare_digest(code.strip().encode(), expected.encode()):
            recent.append(now)
            raise HTTPException(403, "That access code isn't right. Check with your care team lead.")


@router.post("/auth/caregiver/signup", response_model=Me, status_code=201)
def caregiver_signup(body: CaregiverSignup, request: Request, response: Response):
    _check_invite(request, body.invite_code)
    username = _normalize_username(body.username)
    if not USERNAME_RE.match(username):
        raise HTTPException(422, "Usernames are 3–24 letters, numbers, spaces, - or _.")
    if len(body.password) < 8:
        raise HTTPException(422, "Passwords need at least 8 characters.")
    display = _normalize_username(body.display_name) or username
    try:
        with pool.connection() as conn:
            row = conn.execute(
                """INSERT INTO caregivers (username, password_hash, display_name)
                   VALUES (%s, %s, %s) RETURNING caregiver_id, username, display_name""",
                (username, hasher.hash(body.password), display),
            ).fetchone()
            _start_session(conn, "caregiver", row["caregiver_id"], response)
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "That username is taken. Try another.")
    return {"role": "caregiver", "account_id": row["caregiver_id"], "username": row["username"],
            "display_name": row["display_name"], "dominant_hand": None}


# ---- shared --------------------------------------------------------------

@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        with pool.connection() as conn:
            conn.execute("DELETE FROM auth_sessions WHERE token_hash = %s", (_token_hash(token),))
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/auth/me", response_model=Me)
def me(account: dict = Depends(current_account)):
    return account
