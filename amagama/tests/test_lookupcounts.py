#
# Copyright (C) amaGama contributors.
#
# This file is part of amaGama. It is distributed under the GPL3 or
# later license. See the LICENSE file for a copy of the license and
# the AUTHORS.md file for copyright and authorship information.


"""Lookups counted per day, language pair, API version and best match."""

import json
import logging
import threading

import pytest

from amagama import lookupcounts
from amagama.lookupcounts import band, today
from amagama.tests.test_api_v2 import stored, v2  # noqa: F401 - stored is a fixture
from amagama.tests.test_provenance import client, load, query, run  # noqa: F401 - load is a fixture


def counts(pg_connection):
    return query(pg_connection, """SELECT slang, tlang, api, band, lookups
        FROM public.lookup_counts ORDER BY 1, 2, 3, 4""")


@pytest.mark.parametrize("qualities, expected", [
    ([], "none"),
    ([100], "100"),
    ([80, 100, 95], "100"),
    ([99], "90-99"),
    ([90], "90-99"),
    ([89, 75], "75-89"),
    ([74, 70], "<75"),
])
def test_band(qualities, expected):
    assert band([{'quality': q} for q in qualities]) == expected


def test_lookups_are_counted(stored, pg_connection):  # noqa: F811 - fixture
    with client() as c:
        for source in ('Save file', 'Save file', 'Nothing like it'):
            assert c.get('/api/v1/en/af/unit/' + source).status_code == 200
        assert c.get('/tmserver/en/af/unit/Save%20file').status_code == 200
        assert c.get('/api/v1/en/ZU/unit/Save%20file').status_code == 200
        assert v2(c, 'Delete %(count)s files').status_code == 200
        assert v2(c, '<strong>Open</strong> the files').status_code == 200
        # Neither lookups nor counted.
        assert v2(c, 'Save file', av=99).status_code == 409
        assert c.get('/api/v1/en/en/unit/file').status_code == 400
        assert c.get('/api/v1/xx/af/unit/file').status_code == 404
        c.application.lookup_counts.flush()
    assert counts(pg_connection) == [
        ('en', 'af', 1, '100', 3),
        ('en', 'af', 1, 'none', 1),
        ('en', 'af', 2, '100', 1),
        ('en', 'af', 2, '90-99', 1),
        ('en', 'zu', 1, 'none', 1),
    ]
    assert query(pg_connection, "SELECT DISTINCT day FROM public.lookup_counts") == [(today(),)]


def test_flushes_add_up(stored, pg_connection):  # noqa: F811 - fixture
    """Each process adds its own counts to the same rows."""
    apps = [client().application for _ in range(2)]
    for app in apps:
        with app.test_client() as c:
            c.get('/api/v1/en/af/unit/Save%20file')
        app.lookup_counts.flush()
    apps[0].lookup_counts.flush()  # Nothing new: no change.
    assert counts(pg_connection) == [('en', 'af', 1, '100', 2)]


def test_threads(pg_connection, amagama_config):
    run('initdb', '-s', 'en')
    counter = lookupcounts.counter_for(client().application)

    def look_up():
        for _ in range(500):
            counter.record('en', 'af', 1, [{'quality': 100}])

    threads = [threading.Thread(target=look_up) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    counter.flush()
    assert counts(pg_connection) == [('en', 'af', 1, '100', 2000)]


def test_written_when_due(stored, pg_connection, amagama_config):  # noqa: F811 - fixture
    amagama_config(LOOKUP_COUNTS_INTERVAL=0)
    with client() as c:
        c.get('/api/v1/en/af/unit/Save%20file')
    assert counts(pg_connection) == [('en', 'af', 1, '100', 1)]


def test_switched_off(stored, pg_connection, amagama_config):  # noqa: F811 - fixture
    amagama_config(LOOKUP_COUNTS=False)
    with client() as c:
        assert c.application.lookup_counts is None
        assert c.get('/api/v1/en/af/unit/Save%20file').status_code == 200
        assert v2(c, 'Save file').status_code == 200
    assert counts(pg_connection) == []


def test_unsaved_counts_are_dropped(stored, pg_connection, caplog):  # noqa: F811 - fixture
    query(pg_connection, "DROP TABLE public.lookup_counts; SELECT 1")
    with client() as c:
        counter = c.application.lookup_counts
        with caplog.at_level(logging.WARNING):
            for _ in range(2):
                assert c.get('/api/v1/en/af/unit/Save%20file').status_code == 200
                counter.flush()
    assert [r.getMessage() for r in caplog.records if r.module == 'lookupcounts'] == [
        "Lookup counts weren't saved (UndefinedTable); dropping them until they can be."]
    run('init_lookup_counts')
    counter.record('en', 'af', 1, [])
    counter.flush()
    assert counts(pg_connection) == [('en', 'af', 1, 'none', 1)]
    assert not counter._warned


def test_one_thread_writes(pg_connection, amagama_config):
    run('initdb', '-s', 'en')
    counter = lookupcounts.counter_for(client().application)
    counter.record('en', 'af', 1, [])
    with counter._writing:
        counter.flush()  # Another thread is writing: left to it.
    assert counts(pg_connection) == []
    counter.flush()
    assert counts(pg_connection) == [('en', 'af', 1, 'none', 1)]


def test_grant(pg_connection, amagama_config):
    run('initdb', '-s', 'en')
    query(pg_connection, "CREATE ROLE amagama_web; SELECT 1")
    assert "is ready" in run('init_lookup_counts', '--grant', 'amagama_web').output
    assert query(pg_connection, """SELECT has_table_privilege('amagama_web',
        'public.lookup_counts', 'INSERT, UPDATE')""") == [(True,)]
    query(pg_connection, "DROP OWNED BY amagama_web; DROP ROLE amagama_web; SELECT 1")


@pytest.fixture
def counted(pg_connection, amagama_config):
    run('initdb', '-s', 'en')
    query(pg_connection, """INSERT INTO public.lookup_counts VALUES
        ('2026-11-04', 'en', 'af', 1, '100', 5),
        ('2026-11-05', 'en', 'af', 1, '100', 3),
        ('2026-11-05', 'en', 'af', 1, '75-89', 1),
        ('2026-11-05', 'en', 'af', 1, 'none', 2),
        ('2026-11-05', 'en', 'af', 2, '<75', 1),
        ('2026-11-05', 'en', 'zu', 1, 'none', 4),
        ('2026-11-06', 'en', 'af', 2, '90-99', 7);
        SELECT 1""")


def test_command_csv(counted):
    assert run('lookup_counts', '--since', '2026-11-05', '--until', '2026-11-05').output == (
        "day,slang,tlang,api,lookups,matched,100,90-99,75-89,<75\n"
        "2026-11-05,en,af,1,6,4,3,0,1,0\n"
        "2026-11-05,en,af,2,1,1,0,0,0,1\n"
        "2026-11-05,en,zu,1,4,0,0,0,0,0\n")


def test_command_json(counted):
    lines = run('lookup_counts', '--json').output.splitlines()
    assert [json.loads(line)['day'] for line in lines] == [
        '2026-11-04', '2026-11-05', '2026-11-05', '2026-11-05', '2026-11-06']
    assert json.loads(lines[-1]) == {
        'day': '2026-11-06', 'slang': 'en', 'tlang': 'af', 'api': 2, 'lookups': 7,
        'matched': 7, '100': 0, '90-99': 7, '75-89': 0, '<75': 0}
