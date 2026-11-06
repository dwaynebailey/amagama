#
# Copyright (C) amaGama contributors.
#
# This file is part of amaGama. It is distributed under the GPL3 or
# later license. See the LICENSE file for a copy of the license and
# the AUTHORS.md file for copyright and authorship information.


"""Counts of lookups per day, language pair, API version and best match.

Each process counts in memory and adds its counts to the lookup_counts
table at most every LOOKUP_COUNTS_INTERVAL seconds, from the request that
finds them due, on a connection of its own. Nothing about the query or the
client is counted.
"""

import datetime
import logging
import threading
import time

import psycopg2
from psycopg2 import sql
from psycopg2.extras import execute_values

# The bands of the best match's quality, best first; "none" is no match.
BANDS = ("100", "90-99", "75-89", "<75")
NONE = "none"

INIT_SQL = """
CREATE TABLE IF NOT EXISTS public.lookup_counts (
    day DATE NOT NULL,
    slang VARCHAR(32) NOT NULL,
    tlang VARCHAR(32) NOT NULL,
    api SMALLINT NOT NULL,
    band VARCHAR(8) NOT NULL,
    lookups BIGINT NOT NULL,
    PRIMARY KEY (day, slang, tlang, api, band)
);
"""

UPSERT_SQL = """
INSERT INTO public.lookup_counts (day, slang, tlang, api, band, lookups) VALUES %s
ON CONFLICT (day, slang, tlang, api, band)
DO UPDATE SET lookups = lookup_counts.lookups + EXCLUDED.lookups
"""


def band(results):
    """The band of the best quality among results."""
    if not results:
        return NONE
    best = max(result['quality'] for result in results)
    if best >= 100:
        return "100"
    if best >= 90:
        return "90-99"
    if best >= 75:
        return "75-89"
    return "<75"


def today():
    return datetime.datetime.now(datetime.timezone.utc).date()


class LookupCounter:
    """Lookup counts kept in memory and added to the database now and then."""

    def __init__(self, connect, interval=60):
        self._connect = connect
        self.interval = interval
        self._counts = {}
        self._lock = threading.Lock()
        self._writing = threading.Lock()
        self._last = time.monotonic()
        self._warned = False

    def record(self, slang, tlang, api, results):
        key = (today(), slang, tlang, api, band(results))
        with self._lock:
            self._counts[key] = self._counts.get(key, 0) + 1
        if time.monotonic() - self._last >= self.interval:
            self.flush()

    def flush(self):
        """Add the counts so far to the database; another thread writing skips."""
        if not self._writing.acquire(blocking=False):
            return
        try:
            with self._lock:
                counts, self._counts = self._counts, {}
                self._last = time.monotonic()
            if counts:
                self._write(counts)
        finally:
            self._writing.release()

    def _write(self, counts):
        # In key order, so two processes adding the same rows don't deadlock.
        rows = [key + (n,) for key, n in sorted(counts.items())]
        try:
            connection = self._connect()
            try:
                with connection, connection.cursor() as cursor:
                    execute_values(cursor, UPSERT_SQL, rows)
            finally:
                connection.close()
        except psycopg2.Error as e:
            if not self._warned:
                logging.warning("Lookup counts weren't saved (%s); dropping them until "
                                "they can be.", e.__class__.__name__)
                self._warned = True
            return
        self._warned = False


def connect_for(config):
    """A function connecting to the database config names."""
    args = {
        'database': config.get('DB_NAME'),
        'user': config.get('DB_USER'),
        'password': config.get('DB_PASSWORD', ''),
        'connect_timeout': 5,
    }
    for setting, arg in (('DB_HOST', 'host'), ('DB_PORT', 'port')):
        if setting in config:
            args[arg] = config[setting]
    return lambda: psycopg2.connect(**args)


def counter_for(app):
    """The app's counter, or None when LOOKUP_COUNTS is off."""
    if not app.config.get('LOOKUP_COUNTS', True):
        return None
    return LookupCounter(connect_for(app.config), app.config.get('LOOKUP_COUNTS_INTERVAL', 60))


def init_db(cursor, grant=None):
    """Create the table, and let the role grant add to it."""
    cursor.execute(INIT_SQL)
    if grant:
        cursor.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE ON public.lookup_counts TO {}")
                       .format(sql.Identifier(grant)))


def read(cursor, since=None, until=None):
    """Rows of (day, slang, tlang, api, lookups, matched, one count per band)."""
    cursor.execute("""SELECT day, slang, tlang, api, band, lookups FROM public.lookup_counts
        WHERE (%(since)s::date IS NULL OR day >= %(since)s)
          AND (%(until)s::date IS NULL OR day <= %(until)s)
        ORDER BY day, slang, tlang, api""", {'since': since, 'until': until})
    rows = {}
    for day, slang, tlang, api, band_name, lookups in cursor.fetchall():
        row = rows.setdefault((day, slang, tlang, api), dict.fromkeys(BANDS + (NONE,), 0))
        row[band_name] = row.get(band_name, 0) + lookups
    for (day, slang, tlang, api), bands in rows.items():
        matched = sum(bands[name] for name in BANDS)
        yield (day.isoformat(), slang, tlang, api, matched + bands[NONE], matched) + tuple(
            bands[name] for name in BANDS)


HEADER = ("day", "slang", "tlang", "api", "lookups", "matched") + BANDS
