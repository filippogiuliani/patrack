"""Helpers shared by the API modules."""
import datetime
import re

from flask import abort, g, request

TIME_RE = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, 'Invalid request (JSON expected)')
    return data


def valid_date(value, field='date'):
    try:
        return datetime.date.fromisoformat(str(value)).isoformat()
    except ValueError:
        abort(400, f'{field}: invalid date')


def valid_time(value, field='time'):
    """HH:MM, or None when empty."""
    if value in (None, ''):
        return None
    v = str(value)[:5]
    if not TIME_RE.match(v):
        abort(400, f'{field}: invalid time')
    return v


def text(value, max_len=2000):
    return str(value or '').strip()[:max_len]


def rows(cursor):
    return [dict(r) for r in cursor.fetchall()]


def placeholders(values):
    return ','.join('?' * len(values))
