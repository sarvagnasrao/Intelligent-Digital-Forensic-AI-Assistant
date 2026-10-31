"""Manual physical-device records for the active case."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.devices.service import DeviceService


class DeviceDialog(QDialog):
    def __init__(self, session, case_id, user, evidence, parent=None):
        super().__init__(parent)
        self.session, self.case_id, self.user = session, case_id, user
        self.service = DeviceService(session)
        self.setWindowTitle("Physical devices")
        layout = QVBoxLayout(self)
        notice = QLabel("Investigator-entered records only; links do not establish identity.")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        form = QFormLayout()
        self.label = QLineEdit()
        self.serial = QLineEdit()
        self.description = QLineEdit()
        form.addRow("Device label", self.label)
        form.addRow("Serial number (optional)", self.serial)
        form.addRow("Description (optional)", self.description)
        layout.addLayout(form)
        create = QPushButton("Add device")
        create.clicked.connect(self._create)
        layout.addWidget(create)
        self.devices = QComboBox()
        self.evidence = QComboBox()
        for combo in (self.devices, self.evidence):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(12)
        for item in evidence:
            if item.removed_at is None:
                self.evidence.addItem(f"{item.evidence_id} — {item.name}", item.id)
        form2 = QFormLayout()
        form2.addRow("Device", self.devices)
        form2.addRow("Evidence", self.evidence)
        layout.addLayout(form2)
        details = QScrollArea()
        details.setWidgetResizable(True)
        details.setMinimumHeight(120)
        details_content = QWidget()
        details_layout = QVBoxLayout(details_content)
        self.candidates = QLabel()
        self.candidates.setWordWrap(True)
        self.candidates.setTextFormat(Qt.TextFormat.PlainText)
        details_layout.addWidget(self.candidates)
        self.evidence.currentIndexChanged.connect(self._show_candidates)
        self.links = QLabel()
        self.links.setWordWrap(True)
        self.links.setTextFormat(Qt.TextFormat.PlainText)
        details_layout.addWidget(self.links)
        details_layout.addStretch()
        details.setWidget(details_content)
        layout.addWidget(details, 1)
        self.devices.currentIndexChanged.connect(self._show_links)
        buttons = QHBoxLayout()
        link = QPushButton("Link evidence")
        link.clicked.connect(self._link)
        buttons.addWidget(link)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self._refresh()
        self._show_candidates()

    def _show_candidates(self):
        evidence_id = self.evidence.currentData()
        items = self.service.identification_candidates(self.case_id, evidence_id) if evidence_id else []
        heading = ("Identifier leads — physical device unknown; needs review. "
                   "These may describe another device and do not establish identity or a link.")
        lines = [
            f"{x.identifier_type}: {x.value} | artifact {x.artifact_id} | "
            f"path: {x.source_path or 'unknown'} | characters {x.start_offset}–{x.end_offset}\n"
            f"Context: {x.context}"
            for x in items
        ]
        self.candidates.setText(heading + "\n" + ("\n\n".join(lines) or "No source-backed leads available."))

    def _refresh(self):
        self.devices.clear()
        for device in self.service.list_devices(self.case_id):
            suffix = f" — serial: {device.serial_number}" if device.serial_number else ""
            self.devices.addItem(device.label + suffix, device.id)
        self._show_links()

    def _show_links(self):
        device_id = self.devices.currentData()
        items = self.service.linked_evidence(self.case_id, device_id) if device_id else []
        self.links.setText(
            "Linked evidence: "
            + (", ".join(f"{x.evidence_id} ({x.name})" for x in items) or "None")
        )

    def _create(self):
        try:
            self.service.create(
                self.case_id,
                self.user,
                self.label.text(),
                self.description.text(),
                self.serial.text(),
            )
            self.session.commit()
            self.label.clear()
            self.serial.clear()
            self.description.clear()
            self._refresh()
        except Exception as exc:
            self.session.rollback()
            QMessageBox.warning(self, "Device", str(exc))

    def _link(self):
        if not self.devices.currentData() or not self.evidence.currentData():
            QMessageBox.warning(self, "Device", "Choose a device and evidence item.")
            return
        try:
            self.service.link_evidence(
                self.case_id, self.devices.currentData(), self.evidence.currentData(), self.user
            )
            self.session.commit()
            self._show_links()
        except Exception as exc:
            self.session.rollback()
            QMessageBox.warning(self, "Device", str(exc))
