"""The V&V view (§7.7).

"A dedicated view, because V&V is a workflow rather than a dialog."

Three tabs mirroring §6.9. Only the first ships in v1.0; the other two say what
they will hold and which release brings it, because §7.9's "no dead ends" applies
to unbuilt software as much as to error states.

**The provenance strip is not decoration.** §7.7: "the most common way a V&V
table becomes wrong is that it outlives the case it describes". So the case,
OpenFOAM version and turbulence configuration the displayed numbers came from are
named above them, always, and change the moment the case does.

**No number appears without its caveats** (§7.9 rule 6). The first-cell height
carries the correlation that produced it and the accuracy claimed for it; the y+
audit carries the band it was judged against. A number that looks authoritative
and is not is worse than no number.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from foamwb.services.advisor import (
    Answers,
    Compute,
    Recommendation,
    load_catalogue,
    recommend,
    wall_treatments_for,
)
from foamwb.services.apply_turbulence import (
    apply_turbulence,
    current_choice,
    plan_apply,
    wall_patches,
)
from foamwb.services.case import Case, CaseService
from foamwb.services.turbulence import (
    boundary_layer_cells,
    first_cell_height,
    inlet_turbulence,
)
from foamwb.services.yplus import Verdict, audit, read_y_plus
from foamwb.ui.theme import Palette

__all__ = ["VandVView"]

#: How wide a value control in the consequences column may get, in pixels.
_FIELD_WIDTH = 300

#: The narrowest each of the three columns may become, in pixels.
#:
#: The questionnaire gets the largest floor because a check box cannot wrap or
#: elide its own text — Qt simply cuts it off — so "Resolve the turbulent
#: structures, not just their average" either fits or is silently truncated into
#: a different question. The other two hold wrapping text and can be narrowed
#: without losing anything.
_PANE_MINIMUMS = (400, 220, 260)

#: The questionnaire, in §6.9.1's order. Data so the widget and the answers
#: cannot drift apart, and so a new question is one entry rather than three edits.
_QUESTIONS: tuple[tuple[str, str], ...] = (
    ("external", "external_flow"),
    ("separation", "separation"),
    ("adverse_pressure_gradient", "adverse_pressure"),
    ("swirl", "swirl"),
    ("transition", "transition"),
    ("buoyancy", "buoyancy"),
    ("unsteady", "unsteady"),
    ("scale_resolving", "scale_resolving"),
    ("compressible", "compressible"),
    ("resolve_near_wall", "resolve_near_wall"),
)


class VandVView(QWidget):
    """Verification and validation, as a workflow."""

    case_changed = Signal()

    def __init__(
        self,
        palette: Palette,
        labels: dict[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette
        self._labels = labels
        self._catalogue = load_catalogue()
        self._cases = CaseService()
        self._case: Case | None = None
        self._dictionary_name = ""
        self._version = ""
        self._selected: Recommendation | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        self._provenance = QLabel()
        self._provenance.setObjectName("provenanceStrip")
        self._provenance.setWordWrap(True)
        layout.addWidget(self._provenance)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_turbulence(labels), labels["vv_turbulence_tab"])
        self._tabs.addTab(
            _Deferred(labels["vv_mesh_study_title"], labels["vv_mesh_study_body"]),
            labels["vv_mesh_study_tab"],
        )
        self._tabs.addTab(
            _Deferred(labels["vv_validation_title"], labels["vv_validation_body"]),
            labels["vv_validation_tab"],
        )
        layout.addWidget(self._tabs, stretch=1)

        self._refresh_provenance()
        self._recompute()

    # -- construction ------------------------------------------------------

    def _build_turbulence(self, labels: dict[str, str]) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_questionnaire(labels))
        splitter.addWidget(self._build_shortlist(labels))
        splitter.addWidget(self._build_consequences(labels))
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 3)
        # A splitter refuses to shrink a pane below its minimum size hint, and
        # three panes that each ask for what they would *like* add up to more
        # than the window can give — so the third one was drawn past the right
        # edge and could only be read by scrolling sideways, while the first two
        # cut their text off mid-word. Stating a floor each pane can actually
        # live at is what keeps all three legible.
        for index, minimum in enumerate(_PANE_MINIMUMS):
            splitter.widget(index).setMinimumWidth(minimum)
        splitter.setChildrenCollapsible(False)

        # Below the sum of those floors the columns cannot all fit, and the two
        # honest answers are to scroll or to clip. Scrolling is the one that
        # still shows the user everything: the window's 960px minimum (§7.1) with
        # the workflow panel open is exactly that case, and Ctrl+B closing the
        # panel is what makes it fit again.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(splitter)
        return scroll

    def _build_questionnaire(self, labels: dict[str, str]) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 8, 0)
        column.setSpacing(6)

        heading = QLabel(labels["vv_questionnaire"])
        heading.setProperty("role", "subheading")
        column.addWidget(heading)

        note = QLabel(labels["vv_questionnaire_note"])
        note.setProperty("role", "muted")
        note.setWordWrap(True)
        column.addWidget(note)

        self._answers: dict[str, QCheckBox] = {}
        for attribute, key in _QUESTIONS:
            box = QCheckBox(labels[f"q_{key}"])
            box.setToolTip(labels[f"q_{key}_help"])
            box.toggled.connect(self._recompute)
            self._answers[attribute] = box
            column.addWidget(box)

        row = QHBoxLayout()
        row.addWidget(QLabel(labels["q_compute"]))
        self._compute = QComboBox()
        for value in Compute:
            self._compute.addItem(labels[f"compute_{value.value}"], value)
        self._compute.setCurrentIndex(1)
        self._compute.currentIndexChanged.connect(self._recompute)
        row.addWidget(self._compute, stretch=1)
        column.addLayout(row)
        column.addStretch(1)
        return page

    def _build_shortlist(self, labels: dict[str, str]) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(8, 0, 8, 0)
        column.setSpacing(6)

        heading = QLabel(labels["vv_shortlist"])
        heading.setProperty("role", "subheading")
        column.addWidget(heading)

        note = QLabel(labels["vv_shortlist_note"])
        note.setProperty("role", "muted")
        note.setWordWrap(True)
        column.addWidget(note)

        self._shortlist = QListWidget()
        self._shortlist.setAccessibleName(labels["vv_shortlist"])
        self._shortlist.setWordWrap(True)
        # Word wrap alone is not enough: while a horizontal scroll bar is
        # available, the list lays each entry out at its natural width and offers
        # to scroll to the rest, so the reason a model is "known to fail" was
        # being cut off mid-sentence. Refusing the scroll bar is what makes the
        # wrap take effect.
        self._shortlist.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._shortlist.currentItemChanged.connect(self._on_model_selected)
        column.addWidget(self._shortlist, stretch=1)

        self._current_note = QLabel()
        self._current_note.setWordWrap(True)
        self._current_note.setProperty("role", "muted")
        column.addWidget(self._current_note)
        return page

    def _build_consequences(self, labels: dict[str, str]) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(8, 0, 0, 0)
        column.setSpacing(8)

        heading = QLabel(labels["vv_consequences"])
        heading.setProperty("role", "subheading")
        column.addWidget(heading)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        # "Kinematic viscosity (m²/s)" beside its control needs more width than
        # this pane gets on a small display; wrapping the label above the control
        # is what lets the row narrow instead of clipping.
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        self._treatment = QComboBox()
        self._treatment.setMaximumWidth(_FIELD_WIDTH)
        self._treatment.currentIndexChanged.connect(self._recompute_numbers)
        form.addRow(labels["vv_wall_treatment"], self._treatment)

        self._velocity = _spin(1.0, 0.001, 1e6, 3)
        self._length = _spin(1.0, 1e-6, 1e6, 4)
        self._viscosity = _spin(1.5e-5, 1e-12, 1.0, 10)
        self._intensity = _spin(5.0, 0.01, 50.0, 2)
        for widget, key in (
            (self._velocity, "vv_velocity"),
            (self._length, "vv_length"),
            (self._viscosity, "vv_viscosity"),
            (self._intensity, "vv_intensity"),
        ):
            widget.valueChanged.connect(self._recompute_numbers)
            form.addRow(labels[key], widget)
        column.addLayout(form)

        self._numbers = QLabel()
        self._numbers.setWordWrap(True)
        self._numbers.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        column.addWidget(self._numbers)

        self._caveat = QLabel()
        self._caveat.setWordWrap(True)
        self._caveat.setProperty("role", "muted")
        column.addWidget(self._caveat)

        self._apply_button = QPushButton(labels["vv_apply"])
        self._apply_button.clicked.connect(self.apply_selection)
        self._apply_button.setEnabled(False)
        column.addWidget(self._apply_button)

        audit_heading = QLabel(labels["vv_audit"])
        audit_heading.setProperty("role", "subheading")
        column.addWidget(audit_heading)

        self._audit_note = QLabel()
        self._audit_note.setWordWrap(True)
        column.addWidget(self._audit_note)

        self._audit_table = QTableWidget()
        self._audit_table.setColumnCount(4)
        self._audit_table.setHorizontalHeaderLabels(
            [labels["vv_patch"], labels["vv_min"], labels["vv_max"], labels["vv_verdict"]]
        )
        self._audit_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._audit_table.setAccessibleName(labels["vv_audit"])
        self._audit_table.setVisible(False)
        column.addWidget(self._audit_table)

        column.addStretch(1)
        scroll.setWidget(page)
        return scroll

    # -- content -----------------------------------------------------------

    def set_case(self, case: Case | None, *, version: str = "", dictionary_name: str = "") -> None:
        """Attach a case and the release it will run against."""
        self._case = case
        self._version = version
        self._dictionary_name = dictionary_name
        self._refresh_provenance()
        self._recompute()
        self.refresh_audit()

    def _refresh_provenance(self) -> None:
        """§7.7's strip: what the numbers below describe."""
        if self._case is None:
            self._provenance.setText(self._labels["vv_no_case"])
            return
        model, block = (
            current_choice(self._case, dictionary_name=self._dictionary_name)
            if self._dictionary_name
            else (None, None)
        )
        self._provenance.setText(
            self._labels["vv_provenance"].format(
                self._case.name,
                self._version or self._labels["vv_unknown_version"],
                f"{block}/{model}" if model else self._labels["vv_no_model"],
            )
        )

    # -- advising ----------------------------------------------------------

    @property
    def answers(self) -> Answers:
        # Compute is coerced rather than taken as-is: it is a StrEnum, and Qt
        # stores enum data as the plain string, so currentData() comes back as
        # str. Without this the advisor's cost comparison would fail on the
        # first recommendation.
        return Answers(
            **{name: box.isChecked() for name, box in self._answers.items()},
            compute=Compute(self._compute.currentData()),
        )

    @Slot()
    def _recompute(self) -> None:
        """Re-rank on every answer, so the shortlist tracks the questionnaire."""
        answers = self.answers
        self._shortlist.clear()
        for entry in recommend(answers):
            item = QListWidgetItem(self._describe(entry))
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self._shortlist.addItem(item)
        if self._shortlist.count():
            self._shortlist.setCurrentRow(0)
        self._show_current_model_note(answers)

    def _describe(self, entry: Recommendation) -> str:
        """FR-VVT2: good at, known to fail, cost — on every entry."""
        parts = [
            self._labels["vv_entry_head"].format(entry.name, entry.model.family),
            self._labels["vv_good_at"].format(entry.model.good_at),
            self._labels["vv_fails_at"].format(entry.model.fails_at),
            self._labels["vv_cost"].format(self._labels[f"cost_{entry.model.cost}"]),
        ]
        parts.extend(self._labels["vv_because"].format(r) for r in entry.reasons)
        parts.extend(self._labels["vv_but"].format(c) for c in entry.caveats)
        return "\n".join(parts)

    def _show_current_model_note(self, answers: Answers) -> None:
        """Account for the model the case already uses (FR-VVT1).

        A model that merely fell off a truncated list explains nothing, so the
        case's own choice is always named and placed.
        """
        if self._case is None or not self._dictionary_name:
            self._current_note.setText("")
            return
        name, _block = current_choice(self._case, dictionary_name=self._dictionary_name)
        if not name:
            self._current_note.setText("")
            return

        from foamwb.services.advisor import explain, rank_of

        entry = explain(name, answers)
        if entry is None:
            self._current_note.setText(self._labels["vv_current_unknown"].format(name))
            return
        why = (
            entry.caveats[0]
            if entry.caveats
            else (entry.reasons[0] if entry.reasons else self._labels["vv_no_factor"])
        )
        self._current_note.setText(
            self._labels["vv_current"].format(name, rank_of(name, answers), why)
        )

    @Slot()
    def _on_model_selected(self, current: QListWidgetItem | None, _previous=None) -> None:
        if current is None:
            self._selected = None
            return
        self._selected = current.data(Qt.ItemDataRole.UserRole)

        # FR-VVT4: only the treatments this model can be used with are offered,
        # so an inconsistent pairing is unreachable rather than warned about.
        self._treatment.blockSignals(True)
        self._treatment.clear()
        for treatment in wall_treatments_for(self._selected.model, self._catalogue):
            self._treatment.addItem(treatment.label, treatment)
        self._treatment.blockSignals(False)
        self._recompute_numbers()

    # -- numbers -----------------------------------------------------------

    @Slot()
    def _recompute_numbers(self) -> None:
        """The coupled consequences panel (§7.7).

        Recomputed together because they *are* coupled: the wall treatment sets
        the target y+, which sets the first cell height, which sets the layer
        count. Showing them independently would let the panel display a
        combination that cannot exist.
        """
        treatment = self._treatment.currentData()
        if self._selected is None or treatment is None:
            self._numbers.setText("")
            self._caveat.setText("")
            self._apply_button.setEnabled(False)
            return

        low, high = treatment.target_y_plus
        target = 1.0 if high <= 1 else (low + high) / 2

        height = first_cell_height(
            velocity=self._velocity.value(),
            length=self._length.value(),
            kinematic_viscosity=self._viscosity.value(),
            target_y_plus=target,
        )
        layers = boundary_layer_cells(
            first_height=height.height, total_thickness=self._length.value() * 0.02
        )
        inlet = inlet_turbulence(
            velocity=self._velocity.value(),
            intensity=self._intensity.value() / 100.0,
            length_scale=max(self._length.value() * 0.07, 1e-9),
        )

        lines = [
            self._labels["vv_target"].format(f"{low:g}", f"{high:g}", f"{target:g}"),
            self._labels["vv_first_cell"].format(f"{height.height:.3e}"),
            self._labels["vv_layers"].format(layers),
            self._labels["vv_reynolds"].format(f"{height.reynolds:.3e}"),
        ]
        lines.extend(
            self._labels["vv_inlet"].format(name, f"{value:.4g}", inlet.formulas[name])
            for name, value in inlet.for_fields(self._selected.model.fields).items()
        )
        self._numbers.setText("\n".join(lines))
        # Every number travels with what produced it (§7.9 rule 6).
        self._numbers.setToolTip(height.formula)
        self._caveat.setText(
            self._labels["vv_caveat"].format(height.correlation, height.accuracy_note)
        )
        self._apply_button.setEnabled(self._case is not None and bool(self._dictionary_name))

    # -- applying ----------------------------------------------------------

    def apply_selection(self) -> bool:
        """Write the chosen model and its wall conditions (FR-VVT9)."""
        treatment = self._treatment.currentData()
        if self._case is None or self._selected is None or treatment is None:
            return False

        plan = plan_apply(
            self._case,
            self._selected.model,
            treatment,
            dictionary_name=self._dictionary_name,
        )
        if plan.blocked:
            self._caveat.setText(plan.blocked)
            self._caveat.setStyleSheet(f"color: {self._palette.broken};")
            return False

        result = apply_turbulence(self._case, plan, service=self._cases)
        self._caveat.setStyleSheet(f"color: {self._palette.text_muted};")
        self._caveat.setText(
            self._labels["vv_applied"].format(
                self._selected.name, ", ".join(p.name for p in result.written) or "—"
            )
        )
        self._refresh_provenance()
        self.case_changed.emit()
        return result.changed_anything

    # -- audit -------------------------------------------------------------

    def refresh_audit(self) -> None:
        """Show what the last run achieved (FR-VVT7)."""
        self._audit_table.setRowCount(0)
        if self._case is None:
            self._audit_table.setVisible(False)
            self._audit_note.setText("")
            return

        patches = read_y_plus(self._case.path)
        if not patches:
            self._audit_table.setVisible(False)
            self._audit_note.setText(
                self._labels["vv_audit_none"]
                if wall_patches(self._case)
                else self._labels["vv_audit_no_walls"]
            )
            self._audit_note.setStyleSheet(f"color: {self._palette.text_muted};")
            return

        treatment = self._treatment.currentData()
        model = self._selected.model if self._selected else None
        result = audit(patches, treatment=treatment, model=model)

        self._audit_table.setVisible(True)
        self._audit_table.setRowCount(len(result.patches))
        for row, verdict in enumerate(result.patches):
            cells = [
                verdict.name,
                f"{verdict.patch.minimum:.3g}",
                f"{verdict.patch.maximum:.3g}",
                self._labels[f"verdict_{verdict.verdict.value}"],
            ]
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(verdict.message)
                if column == 3:
                    item.setForeground(_brush(self._colour_for(verdict.verdict)))
                self._audit_table.setItem(row, column, item)

        self._audit_note.setText(
            self._labels["vv_audit_summary"].format(
                self._labels[f"verdict_{result.verdict.value}"],
                ", ".join(result.offending) or "—",
            )
        )
        self._audit_note.setStyleSheet(f"color: {self._colour_for(result.verdict)};")

    def _colour_for(self, verdict: Verdict) -> str:
        return {
            Verdict.PASS: self._palette.ready,
            Verdict.WARN: self._palette.degraded,
            Verdict.FAIL: self._palette.broken,
        }[verdict]

    # -- for tests ---------------------------------------------------------

    @property
    def provenance_text(self) -> str:
        return self._provenance.text()

    @property
    def shortlist_names(self) -> list[str]:
        return [
            self._shortlist.item(i).data(Qt.ItemDataRole.UserRole).name
            for i in range(self._shortlist.count())
        ]

    @property
    def shortlist_text(self) -> str:
        return "\n".join(self._shortlist.item(i).text() for i in range(self._shortlist.count()))

    @property
    def treatment_options(self) -> list[str]:
        return [self._treatment.itemText(i) for i in range(self._treatment.count())]

    @property
    def numbers_text(self) -> str:
        return self._numbers.text()

    @property
    def caveat_text(self) -> str:
        return self._caveat.text()

    @property
    def current_model_note(self) -> str:
        return self._current_note.text()

    @property
    def audit_rows(self) -> int:
        return self._audit_table.rowCount()

    @property
    def audit_note(self) -> str:
        return self._audit_note.text()

    def set_answer(self, name: str, value: bool) -> None:
        self._answers[name].setChecked(value)

    def select_model(self, name: str) -> bool:
        for index in range(self._shortlist.count()):
            item = self._shortlist.item(index)
            if item.data(Qt.ItemDataRole.UserRole).name == name:
                self._shortlist.setCurrentRow(index)
                return True
        return False

    def select_treatment(self, key: str) -> bool:
        for index in range(self._treatment.count()):
            if self._treatment.itemData(index).key == key:
                self._treatment.setCurrentIndex(index)
                return True
        return False


class _Deferred(QFrame):
    """A tab whose module ships in a later release (§7.9 rule 1)."""

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        column = QVBoxLayout(self)
        column.setContentsMargins(24, 20, 24, 20)
        column.setSpacing(8)
        column.setAlignment(Qt.AlignmentFlag.AlignTop)

        heading = QLabel(title)
        heading.setProperty("role", "heading")
        column.addWidget(heading)

        text = QLabel(body)
        text.setProperty("role", "muted")
        text.setWordWrap(True)
        column.addWidget(text)
        self.setAccessibleName(title)


def _spin(value: float, minimum: float, maximum: float, decimals: int) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setDecimals(decimals)
    box.setRange(minimum, maximum)
    box.setValue(value)
    # A spin box asks for whatever width its widest possible value needs, and
    # kinematic viscosity is quoted to ten decimals — so left alone it demands
    # about 180px and drags the whole column past the edge of the window. It is
    # capped instead: the value is still readable, and the panel can be as narrow
    # as the window makes it.
    box.setMaximumWidth(_FIELD_WIDTH)
    box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return box


def _brush(colour: str):
    from PySide6.QtGui import QBrush, QColor

    return QBrush(QColor(colour))
