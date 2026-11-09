"""Authenticated edit leases shared by backend workers on one application host."""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import os
import secrets
import sqlite3
import time

from fastapi import HTTPException, Request

ROOT = Path(os.environ.get('FORECAST_LOCK_DIR', Path(__file__).resolve().parents[2] / '.runtime'))
TTL = 90
COOKIE = 'forecast_session'


def connect(name):
    ROOT.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(ROOT / name, timeout=5)
    connection.row_factory = sqlite3.Row
    return connection


def session_db():
    connection = connect('sessions.sqlite')
    connection.execute('CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, email TEXT, expires REAL)')
    return connection


def issue_session(email):
    token = secrets.token_urlsafe(32)
    with session_db() as db:
        db.execute('DELETE FROM sessions WHERE expires < ?', (time.time(),))
        db.execute('INSERT INTO sessions VALUES (?, ?, ?)', (hashlib.sha256(token.encode()).hexdigest(), email.strip().lower(), time.time() + 28800))
    db.close()
    return token


def identity(request: Request):
    token = request.cookies.get(COOKIE, '')
    digest = hashlib.sha256(token.encode()).hexdigest()
    with session_db() as db:
        row = db.execute('SELECT email FROM sessions WHERE token=? AND expires>?', (digest, time.time())).fetchone()
    db.close()
    if not row:
        raise HTTPException(401, 'Please sign in again to edit forecasts.')
    return digest, row['email']


def state_name(state):
    return (state or 'All').strip().upper()


def state_db(state):
    name = hashlib.sha256(state_name(state).encode()).hexdigest()
    connection = connect(f'state-{name}.sqlite')
    connection.execute('CREATE TABLE IF NOT EXISTS holders (session TEXT, lease TEXT, email TEXT, expires REAL, PRIMARY KEY(session, lease))')
    return connection


def busy(email):
    return HTTPException(409, f'{email} is currently editing this state. You can view its data and edit after they leave edit mode.')


def lease_id(request):
    lease = request.headers.get('X-Planning-Lease', '')
    if not lease or len(lease) > 100:
        raise HTTPException(400, 'The edit session is missing. Reopen edit mode.')
    return lease


@contextmanager
def edit_guard(request, state):
    if state_name(state) == 'ALL':
        yield
        return
    session, email = identity(request)
    lease = lease_id(request)
    db = state_db(state)
    try:
        # Hold the state transaction through the write so expiry or release cannot
        # transfer ownership while a forecast submission is still committing.
        db.execute('BEGIN IMMEDIATE')
        db.execute('DELETE FROM holders WHERE expires <= ?', (time.time(),))
        other = db.execute('SELECT email FROM holders WHERE email <> ? LIMIT 1', (email,)).fetchone()
        if other:
            raise busy(other['email'])
        own = db.execute('SELECT 1 FROM holders WHERE session=? AND lease=?', (session, lease)).fetchone()
        if not own:
            raise HTTPException(409, 'Your edit session has expired. Reopen edit mode before saving.')
        yield
        db.execute('UPDATE holders SET expires=? WHERE session=? AND lease=?', (time.time() + TTL, session, lease))
        db.commit()
    finally:
        db.close()


def acquire(request, state):
    if state_name(state) == 'ALL':
        return {'owned': True, 'owner': None}
    session, email = identity(request)
    lease = lease_id(request)
    db = state_db(state)
    try:
        db.execute('BEGIN IMMEDIATE')
        db.execute('DELETE FROM holders WHERE expires <= ?', (time.time(),))
        other = db.execute('SELECT email FROM holders WHERE email <> ? LIMIT 1', (email,)).fetchone()
        if other:
            raise busy(other['email'])
        db.execute('INSERT OR REPLACE INTO holders VALUES (?, ?, ?, ?)', (session, lease, email, time.time() + TTL))
        db.commit()
        return {'owned': True, 'owner': email}
    finally:
        db.close()


def release(request, state):
    if state_name(state) == 'ALL':
        return
    session, _ = identity(request)
    lease = lease_id(request)
    with state_db(state) as db:
        db.execute('DELETE FROM holders WHERE session=? AND lease=?', (session, lease))
    db.close()


def status(request, state):
    if state_name(state) == 'ALL':
        return {'owner': None, 'blocked': False}
    try:
        _, email = identity(request)
    except HTTPException:
        email = None
    with state_db(state) as db:
        row = db.execute('SELECT email FROM holders WHERE expires>? LIMIT 1', (time.time(),)).fetchone()
    db.close()
    owner = row['email'] if row else None
    return {'owner': owner, 'blocked': bool(owner and owner != email)}


def logout(request):
    token = request.cookies.get(COOKIE, '')
    digest = hashlib.sha256(token.encode()).hexdigest()
    for path in ROOT.glob('state-*.sqlite'):
        with connect(path.name) as db:
            db.execute('DELETE FROM holders WHERE session=?', (digest,))
        db.close()
    with session_db() as db:
        db.execute('DELETE FROM sessions WHERE token=?', (digest,))
    db.close()
