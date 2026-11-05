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
    assert abstraction.ABSTRACTION_VERSION == 1


def test_markers():
    assert [(cls.__name__, marker) for cls, marker in abstraction._CLASSES] == [
        ('XMLTagPlaceable', None),
        ('XMLEntityPlaceable', ''),
        ('PythonFormattingPlaceable', ''),
        ('JavaMessageFormatPlaceable', ''),
        ('FormattingPlaceable', ''),
        ('QtFormattingPlaceable', ''),
        ('UrlPlaceable', ''),
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
])
def test_abstract(text, abstracted):
    assert abstract(text)[0] == abstracted
