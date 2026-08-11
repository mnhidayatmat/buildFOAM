"""Form editors, built from schema data (FR-P1, FR-P7, §5.4).

"Form editors are driven by declarative schema files, not hand-written widgets."
So this module renders *kinds* of field and knows nothing about any particular
dictionary: adding ``fvSolution`` means adding a JSON file, not a widget.

**Saving writes one entry, not a file.** FR-P7 is the guarantee that makes the
form and the text tab safe together (DEC-07): a form save modifies only the keys
the user changed, through :meth:`Document.set`, leaving comments, ordering,
whitespace and directives byte-identical. The form never re-renders the document
from its own state — that is exactly the AST-rebuild §4.2 rejects, and it would
quietly reformat every file a user opened.

**Enums are lists, so an invalid value is unreachable.** Validation still runs,
because a file may already contain something the enum does not list, but the form
itself should not be a way to produce one.

Keys the schema does not cover are *named* rather than silently absent. A user
who cannot find ``functions`` in the form should be told it lives in the text tab,
not left wondering whether the application ate it (§5.4, FR-P6).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from foamwb.services.foamdict import Document
from foamwb.services.schema import Field, FieldKind, Schema
from foamwb.ui.theme import Palette

__all__ = ["FormEditor"]

#: What OpenFOAM writes for a boolean. Reading accepts the aliases; writing
#: emits the spelling the tutorials use, so a form save does not convert a file's
#: whole style.
_YES, _NO = "yes", "no"


class FormEditor(QWidget):
    """Renders a schema over a document and writes edits back through it."""

    saved = Signal(bytes)
    """Bytes to write, produced by :meth:`Document.set` — never re-rendered."""

    def __init__(
        self,
        palette: Palette,
        labels: dict[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._labels = labels
        self._schema: Schema | None = None
        self._document: Document | None = None
        self._editors: dict[str, QWidget] = {}
        self._errors: dict[str, QLabel] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        layout.addWidget(self._scroll, stretch=1)

        self._unknown = QLabel()
        self._unknown.setProperty("role", "muted")
        self._unknown.setWordWrap(True)
        layout.addWidget(self._unknown)

        self._save_button = QPushButton(labels["save"])
        self._save_button.setDefault(True)
        self._save_button.clicked.connect(self.save)
        self._save_button.setEnabled(False)
        layout.addWidget(self._save_button, alignment=Qt.AlignmentFlag.AlignRight)

    # -- content -----------------------------------------------------------

    def set_document(self, schema: Schema, document: Document) -> None:
        """Render a schema over a parsed dictionary."""
        self._schema = schema
        self._document = document
        self._editors.clear()
        self._errors.clear()

        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(4, 4, 4, 4)
        form.setSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        for field in schema.fields:
            if not field.applies_to(document):
                # Not hidden arbitrarily: the case does not read it. Showing
                # maxCo with adjustTimeStep off would invite an edit with no
                # effect, which is worse than not offering it.
                continue
            value = document.get(field.key)
            if value is None and not field.required:
                continue

            editor = self._make_editor(field, value)
            self._editors[field.key] = editor

            error = QLabel()
            error.setVisible(False)
            error.setWordWrap(True)
            error.setStyleSheet(f"color: {self._palette.broken};")
            self._errors[field.key] = error

            holder = QWidget()
            column = QVBoxLayout(holder)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(2)
            column.addWidget(editor)
            column.addWidget(error)
            if field.help:
                hint = QLabel(field.help)
                hint.setProperty("role", "muted")
                hint.setWordWrap(True)
                # A word-wrapped label reports the height of a single line until
                # it is told to compute height from width, so without this the
                # row is laid out too short and the help text overlaps whatever
                # is beneath it.
                policy = hint.sizePolicy()
                policy.setHeightForWidth(True)
                policy.setVerticalPolicy(QSizePolicy.Policy.MinimumExpanding)
                hint.setSizePolicy(policy)
                column.addWidget(hint)

            label = QLabel(field.title)
            label.setToolTip(field.key)
            form.addRow(label, holder)

        self._scroll.setWidget(page)
        self._show_unknown_keys(schema, document)
        self._save_button.setEnabled(False)

    def _make_editor(self, field: Field, value: str | None) -> QWidget:
        if field.kind is FieldKind.BOOL:
            box = QCheckBox()
            box.setChecked(_as_bool(value))
            box.setAccessibleName(field.title)
            box.toggled.connect(lambda _on, key=field.key: self._on_edited(key))
            return box

        if field.kind is FieldKind.ENUM and field.values:
            combo = QComboBox()
            combo.addItems(field.values)
            if value is not None and value not in field.values:
                # The file already holds something the enum does not list. It is
                # shown rather than silently replaced with the first legal value,
                # which would change the case without the user asking.
                combo.insertItem(0, value)
            combo.setCurrentText(value or field.values[0])
            combo.setAccessibleName(field.title)
            combo.currentTextChanged.connect(lambda _t, key=field.key: self._on_edited(key))
            return combo

        line = QLineEdit(value or "")
        line.setAccessibleName(field.title)
        line.textChanged.connect(lambda _t, key=field.key: self._on_edited(key))
        return line

    def _show_unknown_keys(self, schema: Schema, document: Document) -> None:
        """Say what the form does not reach, and how (§5.4, FR-P6).

        Two different facts, so two different sentences. An unknown key is
        entirely in the text tab. A *partly* covered group has some settings here
        and the rest there — ``divSchemes`` shows its default while its
        per-operator entries stay in the text — and conflating the two would tell
        the user to look in the wrong place.
        """
        lines: list[str] = []
        if unknown := schema.unknown_keys(document):
            lines.append(self._labels["not_in_form"].format(", ".join(sorted(unknown))))
        if partial := schema.partial_groups(document):
            lines.append(self._labels["partly_in_form"].format(", ".join(partial)))

        self._unknown.setText("\n".join(lines))
        self._unknown.setVisible(bool(lines))

    # -- editing -----------------------------------------------------------

    def value_of(self, key: str) -> str:
        editor = self._editors[key]
        if isinstance(editor, QCheckBox):
            return _YES if editor.isChecked() else _NO
        if isinstance(editor, QComboBox):
            return editor.currentText()
        return editor.text()

    def _on_edited(self, key: str) -> None:
        """Validate on entry (FR-P1), and enable saving."""
        assert self._schema is not None
        field = self._schema.field(key)
        error = self._errors.get(key)
        if field is not None and error is not None:
            problem = field.check(self.value_of(key))
            error.setText(problem or "")
            error.setVisible(problem is not None)
        self._save_button.setEnabled(self._is_valid())

    def _is_valid(self) -> bool:
        assert self._schema is not None
        return all(
            self._schema.field(key) is None
            or self._schema.field(key).check(self.value_of(key)) is None
            for key in self._editors
        )

    @property
    def changes(self) -> dict[str, str]:
        """Keys whose value the user actually changed, and their new values.

        Compared by *meaning*, not by spelling. OpenFOAM accepts ``yes``/``no``,
        ``true``/``false`` and ``on``/``off``, and a checkbox has no way to report
        which of them the file used. Comparing the strings would make every
        boolean look edited, so saving one field would silently rewrite every
        other boolean in the file into this application's preferred spelling —
        precisely the quiet reformatting FR-P7 forbids, and invisible in the form
        that caused it.
        """
        if self._document is None or self._schema is None:
            return {}

        changed: dict[str, str] = {}
        for key in self._editors:
            current = self._document.get(key) or ""
            new = self.value_of(key)
            field = self._schema.field(key)

            if field is not None and field.kind is FieldKind.BOOL:
                if _as_bool(new) != _as_bool(current):
                    changed[key] = new
                continue

            if _normalise(new) != _normalise(current):
                changed[key] = new
        return changed

    def save(self) -> bool:
        """Apply the changed entries and emit the resulting bytes (FR-P7).

        Each change goes through :meth:`Document.set`, so the diff is one line per
        edited entry and every other byte in the file is untouched.
        """
        if self._document is None or not self._is_valid():
            return False

        changes = self.changes
        if not changes:
            return False

        for key, value in changes.items():
            self._document.set(key, value)

        self._save_button.setEnabled(False)
        self.saved.emit(self._document.render_bytes())
        return True

    # -- for tests ---------------------------------------------------------

    @property
    def keys(self) -> list[str]:
        return list(self._editors)

    def set_value(self, key: str, value: str) -> None:
        editor = self._editors[key]
        if isinstance(editor, QCheckBox):
            editor.setChecked(_as_bool(value))
        elif isinstance(editor, QComboBox):
            editor.setCurrentText(value)
        else:
            editor.setText(value)

    def error_of(self, key: str) -> str:
        return self._errors[key].text()

    @property
    def can_save(self) -> bool:
        return self._save_button.isEnabled()

    @property
    def unknown_text(self) -> str:
        # isVisibleTo, not isVisible: the latter is False for every descendant of
        # a window that has not been shown, so this would report "" for reasons
        # having nothing to do with whether there are unknown keys.
        return self._unknown.text() if self._unknown.isVisibleTo(self) else ""


def _as_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"yes", "true", "on", "1"}


def _normalise(value: str) -> str:
    return " ".join(value.split())
