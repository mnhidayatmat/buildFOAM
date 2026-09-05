"""The graphics window (§7.1, DEC-21): the centre of the screen, tabbed.

Fluent's graphics window is the persistent centre of its window. It is never
replaced by a form; forms live in the task page, and what appears here is a
*document* — the mesh, the residual plot, a contour — each a tab across the
top. The same here. Two tabs are always present: **Mesh**, which shows the
imported surface, and **Scaled Residuals**, which fills as the solver runs.
Everything else that is too wide for a task page — the boundary matrix, the
dictionary editors, the guide — is a document beside them rather than a modal
in front of them, so the outline stays reachable while it is open.

Documents are registered under keys the outline's nodes name, so a node can
say which tab it raises and the shell need not know the order the tabs were
added in.
"""

from __future__ import annotations

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

__all__ = ["GraphicsWindow"]


class GraphicsWindow(QWidget):
    """Named document tabs."""

    def __init__(self, labels: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("graphicsWindow")
        self._labels = labels
        self._keys: dict[str, int] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setObjectName("graphicsTabs")
        self._tabs.setDocumentMode(True)
        self._tabs.setAccessibleName(labels["graphics_window"])
        layout.addWidget(self._tabs)

    def add_document(self, key: str, widget: QWidget) -> None:
        self._keys[key] = self._tabs.addTab(widget, self._labels[f"doc.{key}"])

    def show_document(self, key: str) -> bool:
        """Raise one document. Unknown names change nothing.

        Not ``show``: that is ``QWidget``'s, and shadowing it with a different
        signature breaks every ordinary call to it.
        """
        index = self._keys.get(key)
        if index is None:
            return False
        self._tabs.setCurrentIndex(index)
        return True

    @property
    def current(self) -> str:
        current = self._tabs.currentIndex()
        return next((key for key, index in self._keys.items() if index == current), "")

    @property
    def documents(self) -> list[str]:
        return list(self._keys)

    def widget(self, key: str) -> QWidget:
        return self._tabs.widget(self._keys[key])

    def title_of(self, key: str) -> str:
        return self._tabs.tabText(self._keys[key])
