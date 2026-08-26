#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2010-2014 Zuza Software Foundation
#
# This file is part of amaGama.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""PostgreSQL access and helpers."""

import threading

from flask import g, got_request_exception
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


class PersistentConnectionPool:
    """A pool that assigns persistent connections to different threads.

    Until a thread puts away its connection it will always get the same
    connection object back from successive `!getconn()` calls, and a thread
    can't use more than one connection from the pool at a time. amaGama
    depends on this: within one request, multiple get_cursor() calls need
    to share one open transaction (e.g. so an INSERT in one call is visible
    to a SELECT in the next, before the request-end commit).

    psycopg_pool.ConnectionPool doesn't provide this affinity itself -
    plain getconn() calls just return any available connection - so this
    wraps one to add it back, the same way the psycopg2-based
    PersistentConnectionPool this replaces did (that one subclassed
    psycopg2's own AbstractConnectionPool, keying its used-connections dict
    by thread id; psycopg_pool has no equivalent base class to subclass, so
    this uses a plain threading.local() instead).
    """

    def __init__(self, minconn, maxconn, **kwargs):
        self._pool = ConnectionPool(
            min_size=minconn, max_size=maxconn, kwargs=kwargs, open=True)
        self._local = threading.local()

    def getconn(self):
        """Return this thread's connection, checking one out if needed."""
        conn = getattr(self._local, 'connection', None)
        if conn is None:
            conn = self._pool.getconn()
            self._local.connection = conn
        return conn

    def putconn(self, conn=None):
        """Put away this thread's connection."""
        conn = conn or getattr(self._local, 'connection', None)
        if conn is None:
            return
        self._local.connection = None
        self._pool.putconn(conn)

    def closeall(self):
        """Close all connections (even the one currently in use.)"""
        self._pool.close()


class PostGres(object):
    INIT_SQL = None

    def __init__(self, app=None):
        self.app = None
        self.pool = None
        self._last_schema = {}  # id(conn)-> last used schema on conn

        if app:
            self.init_app(app)

    def cleanup(self, response):
        """Return connection to pool on request end."""
        #FIXME: we should have better dirty detection, maybe wrap up insert
        # queries?
        if getattr(g, 'transaction_dirty', False):
            connection = self.connection
            if response.status_code < 400:
                connection.commit()
            else:
                connection.rollback()
            self.pool.putconn(connection)
        return response

    def bailout(self, app, exception):
        """Return connection to pool on request ended by unhandled exception."""
        if app.debug and getattr(g, 'transaction_dirty', False):
            self.connection.rollback()
            self.pool.putconn()

    def init_app(self, app):
        self.app = app
        # Read config.
        db_args = {
            'minconn': app.config.get('DB_MIN_CONNECTIONS', 2),
            'maxconn': app.config.get('DB_MAX_CONNECTIONS', 20),
            'dbname': app.config.get('DB_NAME'),
            'user': app.config.get('DB_USER'),
            'password': app.config.get('DB_PASSWORD', ''),
        }
        if 'DB_HOST' in app.config:
            db_args['host'] = app.config.get('DB_HOST')
        if 'DB_PORT' in app.config:
            db_args['port'] = app.config.get('DB_PORT')

        self.pool = PersistentConnectionPool(**db_args)

        app.after_request(self.cleanup)

        got_request_exception.connect(self.bailout, app)

    @property
    def connection(self):
        """Get a thread local database connection object."""
        #FIXME: this is dirty can we detect when in request context?
        try:
            g.transaction_dirty = True
        except Exception:
            # Using connection outside request context.
            pass

        return self.pool.getconn()

    def get_cursor(self, schema=None):
        """Get a database cursor object to be used for making queries.

        The optional schema indicated will cause a SET SCHEMA command, but
        only if required. If schema is None, it means that any previous SET
        SCHEMA command on the connection won't matter (the queries will use
        explicit schemas)."""
        #FIXME: maybe use server side cursors?
        conn = self.connection
        cursor = conn.cursor(row_factory=dict_row)
        if schema and self._last_schema.get(id(conn)) != schema:
            cursor.execute(sql.SQL("SET SCHEMA {}").format(sql.Literal(schema)))
            self._last_schema[id(conn)] = schema
        return cursor

    def init_db(self, *args, **kwargs):
        """Initialize the database."""
        if not self.INIT_SQL:
            return
        cursor = self.get_cursor()
        cursor.execute(self.INIT_SQL)
        cursor.connection.commit()

    def function_exists(self, function):
        """Check if the SQL function already exists in the database."""
        query = """SELECT EXISTS(SELECT proname FROM pg_proc WHERE proname = %(function)s)"""
        cursor = self.get_cursor()
        cursor.execute(query, {'function': function})
        return cursor.fetchone()['exists']

    def table_exists(self, table):
        """Check if table already exists in the database."""
        query = """SELECT EXISTS(SELECT relname FROM pg_class WHERE relname = %(table)s and relkind='r')"""
        cursor = self.get_cursor()
        cursor.execute(query, {'table': table})
        return cursor.fetchone()['exists']

    def drop_table(self, table):
        """Drop the table if it exists."""
        query = sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(sql.Identifier(table))
        cursor = self.get_cursor()
        cursor.execute(query)
        cursor.connection.commit()
