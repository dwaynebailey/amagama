#
# Copyright (C) amaGama contributors.
#
# This file is part of amaGama. It is distributed under the GPL3 or
# later license. See the LICENSE file for a copy of the license and
# the AUTHORS.md file for copyright and authorship information.


"""Sources store their abstract: each placeable reduced to a marker (#3603)."""

import pytest

from amagama.abstraction import ABSTRACTION_VERSION
from amagama.tests.test_provenance import client, load, query, run  # noqa: F401 - load is a fixture


def sources(pg_connection, schema='en'):
    return query(pg_connection, """SELECT text, abstract, length, vector::text
        FROM %s.sources ORDER BY text""" % schema)


def lookup(c, source, lang='af'):
    response = c.get('/api/v1/en/%s/unit/' % lang, query_string={'source': source})
    assert response.status_code == 200
    return response.get_json()


def lexemes(vector):
    return sorted(word.split(':')[0].strip("'") for word in vector.split())


@pytest.fixture
def stored(load):  # noqa: F811 - fixture
    run('initdb', '-s', 'en')
    load('gnome-51', 'af', [
        ('Delete %(count)s files', 'Skrap %(count)s lêers'),
        ('Fish &amp; chips', 'Vis &amp; skyfies'),
        ('_Open', '_Open'),
        ('Save file', 'Stoor lêer'),
        ('%s', '%s'),
    ])


class TestStorage(object):

    def test_columns(self, stored, pg_connection):
        rows = {text: row for text, *row in sources(pg_connection)}
        # The abstract is stored only when it isn't the text.
        assert rows['Save file'][:2] == [None, 9]
        assert rows['Delete %(count)s files'][:2] == ['Delete  files', 14]
        assert rows['Fish &amp; chips'][:2] == ['Fish  chips', 12]
        assert rows['_Open'][:2] == ['Open', 4]

    def test_vector_from_abstract(self, stored, pg_connection):
        rows = {text: row for text, *row in sources(pg_connection)}
        assert lexemes(rows['Delete %(count)s files'][2]) == ['delet', 'file']
        # An entity's & is no accelerator, and the entity isn't a word.
        assert lexemes(rows['Fish &amp; chips'][2]) == ['chip', 'fish']
        assert lexemes(rows['_Open'][2]) == ['open']
        # Only placeables: the markers are the words.
        assert lexemes(rows['%s'][2]) == ['amagamamarker1']

    def test_version_recorded(self, stored, pg_connection):
        assert query(pg_connection, "SELECT version FROM en.abstraction") == [
            (ABSTRACTION_VERSION,)]

    def test_write_api(self, stored, amagama_config, pg_connection):
        amagama_config(ENABLE_DATA_ALTERING_API=True)
        with client() as c:
            response = c.put('/api/v1/en/af/unit/', query_string={'source': 'Open %s'},
                             json={'source': 'Open %s', 'target': 'Maak %s oop'})
            assert response.status_code == 200
        assert query(pg_connection, "SELECT abstract, length FROM en.sources "
                     "WHERE text = 'Open %s'") == [('Open ', 6)]


class TestLookupV1(object):

    def test_unchanged_reply(self, stored):
        with client() as c:
            [match] = lookup(c, 'Delete %(count)s files')
        assert match.pop('rank') > 0
        assert match == {'source': 'Delete %(count)s files', 'target': 'Skrap %(count)s lêers',
                         'quality': 100, 'sources': ['gnome-51']}

    def test_quality_stays_raw(self, stored):
        with client() as c:
            [match] = lookup(c, 'Delete %(number)s files')
        assert match['source'] == 'Delete %(count)s files'
        assert match['quality'] < 100

    @pytest.mark.parametrize('source', ['_Open', 'Fish &amp; chips', '%s', 'Save file'])
    def test_finds_itself(self, stored, source):
        with client() as c:
            assert [match['source'] for match in lookup(c, source)] == [source]

    def test_accelerator_of_another_style(self, stored):
        with client() as c:
            assert [match['target'] for match in lookup(c, '&Open')] == ['_Open']

    def test_schema_without_abstracts(self, load, pg_connection):  # noqa: F811 - fixture
        """A schema made before abstracts is searched by its text, as before."""
        run('initdb', '-s', 'en')
        with pg_connection.cursor() as cursor:
            cursor.execute("DROP TABLE en.abstraction")
        pg_connection.commit()
        load('gnome-51', 'af', [('Delete %(count)s files', 'Skrap %(count)s lêers')])
        assert sources(pg_connection)[0][:3] == ('Delete %(count)s files', None, 22)
        with client() as c:
            assert [match['target'] for match in lookup(c, 'Delete %(count)s files')] == [
                'Skrap %(count)s lêers']


def make_old(pg_connection, schema='en'):
    """Make the schema's sources look as if stored before abstracts."""
    with pg_connection.cursor() as cursor:
        cursor.execute("""DROP TABLE %(schema)s.abstraction;
            ALTER TABLE %(schema)s.sources DROP COLUMN abstract;
            UPDATE %(schema)s.sources SET length = length(text),
                vector = TO_TSVECTOR('english', text)""" % {'schema': schema})
    pg_connection.commit()


class TestRecompute(object):

    def test_recompute(self, stored, pg_connection):
        expected = sources(pg_connection)
        make_old(pg_connection)
        result = run('recompute_abstracts', '-s', 'en')
        assert "Recomputed en: 4 sources changed." in result.output
        assert sources(pg_connection) == expected
        assert query(pg_connection, "SELECT version FROM en.abstraction") == [
            (ABSTRACTION_VERSION,)]
        result = run('recompute_abstracts', '-s', 'en')
        assert "Recomputed en: 0 sources changed." in result.output

    def test_recompute_to_version_2(self, load, pg_connection):  # noqa: F811 - fixture
        """Version 1 left {{count}} and %1$@ as text; recomputing gives
        version 2's abstracts and records version 2."""
        run('initdb', '-s', 'en')
        load('gnome-51', 'af', [('{{count}} files', '{{count}} lêers'),
                                ('Open %1$@', 'Maak %1$@ oop')])
        with pg_connection.cursor() as cursor:
            cursor.execute("""UPDATE en.sources SET abstract = NULL, length = length(text),
                    vector = TO_TSVECTOR('english', text);
                UPDATE en.abstraction SET version = 1""")
        pg_connection.commit()
        result = run('recompute_abstracts', '-s', 'en')
        assert "Recomputed en: 2 sources changed." in result.output
        rows = {text: row for text, *row in sources(pg_connection)}
        assert rows['{{count}} files'][:2] == ['\ue001 files', 7]
        assert rows['Open %1$@'][:2] == ['Open \ue001', 6]
        assert query(pg_connection, "SELECT version FROM en.abstraction") == [(2,)]

    def test_recompute_deployed(self, stored, pg_connection):
        expected = sources(pg_connection)
        run('deploy_db', input='y\n')
        make_old(pg_connection)
        run('recompute_abstracts', '-s', 'en')
        assert sources(pg_connection) == expected
        with client() as c:
            assert [match['source'] for match in lookup(c, '_Open')] == ['_Open']

    def test_snapshot_keeps_abstracts(self, stored, pg_connection):
        expected = sources(pg_connection)
        run('snapshot_db', '-s', 'en', '--name', 'legacy')
        run('initdb', '-s', 'en', '--build')
        run('load_snapshot', '-s', 'en', '--name', 'legacy', '--block', 'legacy-2019')
        assert sources(pg_connection, '_build_en') == expected

    def test_old_snapshot_recomputed_on_load(self, stored, pg_connection):
        """A snapshot made before abstracts gets them as it loads."""
        expected = sources(pg_connection)
        run('snapshot_db', '-s', 'en', '--name', 'legacy')
        make_old(pg_connection, '_legacy_en')
        run('initdb', '-s', 'en', '--build')
        run('load_snapshot', '-s', 'en', '--name', 'legacy', '--block', 'legacy-2019')
        assert sources(pg_connection, '_build_en') == expected

    def test_recompute_snapshot(self, stored, pg_connection):
        expected = sources(pg_connection)
        run('snapshot_db', '-s', 'en', '--name', 'legacy')
        make_old(pg_connection, '_legacy_en')
        result = run('recompute_abstracts', '-s', 'en', '--snapshot', 'legacy')
        assert "Recomputed _legacy_en: 4 sources changed." in result.output
        assert sources(pg_connection, '_legacy_en') == expected
        assert query(pg_connection, "SELECT version FROM _legacy_en.abstraction") == [
            (ABSTRACTION_VERSION,)]

    def test_missing_schema(self, stored):
        from amagama.cli import manage
        from click.testing import CliRunner
        result = CliRunner().invoke(manage, ['recompute_abstracts', '-s', 'en',
                                             '--snapshot', 'nothere'])
        assert result.exit_code == 1
        assert "Schema _nothere_en doesn't exist." in result.output
