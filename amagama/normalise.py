#
# Copyright (C) amaGama contributors.
#
# This file is part of amaGama. It is distributed under the GPL3 or
# later license. See the LICENSE file for a copy of the license and
# the AUTHORS.md file for copyright and authorship information.


"""Functionality for text normalisation."""

import re

# An entity's "&" (in "&amp;") is no accelerator marker.
_ENTITY_RE = re.compile(r'&(?:[A-Za-z][\w.-]*|#[0-9]+|#[xX][0-9A-Fa-f]+);')

# The abstraction's markers (amagama.abstraction).
_MARKER_RE = re.compile('[\ue001-\ue00a]')
_WORD_RE = re.compile(r'\w')


def indexing_version(s, checker=None):
    """Transform the given string to something more suitable for indexing."""
    s = strip_accelerator(s, checker)
    s = fix_ellipses(s)
    return s


def abstract_indexing_version(abstract):
    """Transform an abstract to something more suitable for indexing.

    A marker would join the words on either side, so it becomes a space.
    An abstract of only placeables keeps its markers as words, the only
    thing to find it by. The abstraction already removed the accelerator.
    """
    s = _MARKER_RE.sub(' ', abstract)
    if not _WORD_RE.search(s):
        s = _MARKER_RE.sub(lambda m: ' amagamamarker%d ' % (ord(m.group()) - 0xe000), abstract)
    return fix_ellipses(s)


def strip_accelerator(s, checker):
    if not (checker and checker.config.accelmarkers):
        return s

    accel = checker.config.accelmarkers[0]
    plain = _ENTITY_RE.sub(lambda m: ' ' * len(m.group()), s) if accel == '&' else s
    if plain.count(accel) != 1:
        return s

    accel_pos = plain.find(accel)
    accel_char = s[accel_pos+1:accel_pos+2]
    valid_accel = checker.config.sourcelang.validaccel
    if (valid_accel and accel_char in valid_accel) or accel_char.isalnum():
        return s[:accel_pos] + s[accel_pos + 1:]

    return s


def fix_ellipses(s):
    """Fix inconsistent ellipses."""
    # Note that the space before the ellipsis will cause postgres to index it
    # as a lexeme.
    if s.endswith(u'...'):
        return s[:-3] + u' …'
    else:
        return s.replace(u'…', u' …')
