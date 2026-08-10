"""Stand-in for a view whose milestone has not landed.

Present so the shell's view stack is complete from M1: the nav rail, the stack
and the keyboard shortcuts are all driven from one list, and a missing entry
would mean either a rail button that does nothing or a shortcut that silently
fails. Both are worse than a screen that says plainly what is not built yet.

§7.9 rule 1 says every state offers at least one action, and "no dead ends"
applies to unfinished software too: each placeholder names the milestone that
will fill it, so the app never simply stares back.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

__all__ = ["PlaceholderView"]


class PlaceholderView(QWidget):
    def __init__(self, title: str, detail: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        heading = QLabel(title)
        heading.setProperty("role", "heading")
        layout.addWidget(heading)

        body = QLabel(detail)
        body.setProperty("role", "muted")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(body)
        layout.addStretch(1)

        self.setAccessibleName(title)
