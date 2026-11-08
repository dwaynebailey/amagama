#
# Copyright (C) amaGama contributors.
#
# This file is part of amaGama. It is distributed under the GPL3 or
# later license. See the LICENSE file for a copy of the license and
# the AUTHORS.md file for copyright and authorship information.


"""The copy of Virtaal's abstraction must abstract as Virtaal does.

A change here means a change in Virtaal's module: bump ABSTRACTION_VERSION
there, copy the module again and rebuild the database.
"""

import pytest

from amagama import abstraction
from amagama.abstraction import abstract


def test_version():
    assert abstraction.ABSTRACTION_VERSION == 2


def test_markers():
    assert [(cls.__name__, marker) for cls, marker in abstraction._CLASSES] == [
        ('I18NextPlaceable', '\ue001'),
        ('RubyPlaceable', '\ue001'),
        ('FluentReferencePlaceable', '\ue001'),
        ('ApplePlaceable', '\ue001'),
        ('DotNetPlaceable', '\ue001'),
        ('BracePlaceable', '\ue001'),
        ('XMLTagPlaceable', None),
        ('XMLEntityPlaceable', ''),
        ('PythonFormattingPlaceable', ''),
        ('JavaMessageFormatPlaceable', ''),
        ('FormattingPlaceable', ''),
        ('QtFormattingPlaceable', ''),
        ('_UrlPlaceable', ''),
        ('FilePlaceable', ''),
        ('EmailPlaceable', ''),
        ('OptionPlaceable', ''),
        ('NumberPlaceable', ''),
    ]
    assert (abstraction.TAG_OPEN, abstraction.TAG_CLOSE, abstraction.TAG_EMPTY) == (
        '', '', '')


@pytest.mark.parametrize('text, abstracted', [
    ('Delete %(count)s files', 'Delete  files'),
    ('Delete {0} files', 'Delete  files'),
    ('A <b>bold</b> move<br/>', 'A bold move'),
    ('Fish &amp; chips', 'Fish  chips'),
    ('See https://example.org/x now', 'See  now'),
    # A URL ending a sentence leaves the punctuation outside.
    ('See https://example.org.', 'See .'),
    ('See www.example.org.', 'See .'),
    ('Mail me@example.org', 'Mail '),
    ('Use --help', 'Use '),
    ('Page 12', 'Page '),
    # "% d" with a space flag is no variable.
    ('100% done', '% done'),
    ('_Open', 'Open'),
    ('&Save', 'Save'),
    ('_Save _As', '_Save _As'),
    ('Wait...', 'Wait…'),
    # A string with a character from the marker block stays raw.
    ('Icon  %s', 'Icon  %s'),
    # Version 2: other formats' placeholders, in any text.
    ('{{count}} files', '\ue001 files'),
    ('Hello { $user }', 'Hello \ue001'),
    ('Open %1$@', 'Open \ue001'),
    ('Value {0:N2}', 'Value \ue001'),
    ('Save as {name}', 'Save as \ue001'),
    ('Hi %{name}', 'Hi \ue001'),
    ('$t(common.save) now', '\ue001 now'),
    # Not the parsers Virtaal gives only some formats or flags: ICU's
    # plural and a shell variable stay text, as in Virtaal's abstract.
    ('{n, plural, one {# file} other {# files}}', '{n, plural, one {# file} other {# files}}'),
    ('Use $HOME now', 'Use $HOME now'),
])
def test_abstract(text, abstracted):
    assert abstract(text)[0] == abstracted


@pytest.mark.parametrize('query, source, target, expected', [
    ('{{n}} files', '{{count}} files', '{{count}} lêers', '{{n}} lêers'),
    ('Hello { $name }', 'Hello { $user }', 'Hallo { $user }', 'Hallo { $name }'),
    ('Open %2$@', 'Open %1$@', 'Maak %1$@ oop', 'Maak %2$@ oop'),
    ('Value {1:N2}', 'Value {0:N2}', 'Waarde {0:N2}', 'Waarde {1:N2}'),
    ('Save as %s', 'Save as {name}', 'Stoor as {name}', 'Stoor as %s'),
    ('Hi %s', 'Hi %{name}', 'Hallo %{name}', 'Hallo %s'),
])
def test_format_placeholder_round_trip(query, source, target, expected):
    """A match differing only in a placeholder has the query's abstract and
    takes the query's placeholder."""
    assert abstract(query)[0] == abstract(source)[0]
    adapted = abstraction.adapt(query, source, target, 70)
    assert adapted.target == expected
    assert adapted.rebuilt.unresolved == 0
