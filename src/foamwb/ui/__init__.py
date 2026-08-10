"""Presentation layer — PySide6 (Qt 6). The only subtree permitted to import Qt.

Nothing here may be imported by :mod:`foamwb.services`; the dependency runs one
way, enforced by ``tools/check_no_qt.py`` (NFR-M1, §4.1).

Widgets take their user-visible text as constructor arguments rather than looking
it up, so the catalogue in :mod:`foamwb.ui.strings` is the single enumerable set
of translatable strings (NFR-A5) and every widget is testable against fixed text.
"""
