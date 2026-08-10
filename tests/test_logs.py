"""Structured logging (NFR-M4).

The vocabulary tests matter more than the formatter tests: a diagnostics bundle
is only machine-analysable if event names are a closed, well-formed set. A
free-string event that slips through is invisible to triage tooling until
someone notices the gap during an actual support case.
"""

from __future__ import annotations

import json
import logging
import re

import pytest

from foamwb.logs import Event, JsonLinesFormatter, configure, get_logger, log_event


class TestVocabulary:
    def test_every_event_is_dotted_lowercase(self) -> None:
        for event in Event:
            assert re.fullmatch(r"[a-z]+(\.[a-z_]+)+", event.value), event

    def test_event_values_are_unique(self) -> None:
        values = [e.value for e in Event]
        assert len(values) == len(set(values))

    def test_names_and_values_correspond(self) -> None:
        # app.start <-> APP_START. Keeps the enum greppable from a log line.
        for event in Event:
            assert event.name == event.value.replace(".", "_").upper()


class TestFormatter:
    def _record(self, **extra: object) -> logging.LogRecord:
        record = logging.LogRecord(
            name="foamwb.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="ignored",
            args=(),
            exc_info=None,
        )
        for key, value in extra.items():
            setattr(record, key, value)
        return record

    def test_output_is_one_json_object_on_one_line(self) -> None:
        line = JsonLinesFormatter().format(self._record(event=Event.RUN_BEGIN.value, case="cavity"))
        assert "\n" not in line
        assert json.loads(line)["event"] == "run.begin"

    def test_caller_fields_are_serialised_alongside_the_event(self) -> None:
        payload = json.loads(
            JsonLinesFormatter().format(
                self._record(event=Event.RUN_STAGE_END.value, stage="blockMesh", exit_code=0)
            )
        )
        assert payload["stage"] == "blockMesh"
        assert payload["exit_code"] == 0

    def test_standard_record_attributes_are_not_leaked(self) -> None:
        payload = json.loads(JsonLinesFormatter().format(self._record(event="app.start")))
        assert "msecs" not in payload
        assert "relativeCreated" not in payload

    def test_timestamp_is_utc_iso8601_with_milliseconds(self) -> None:
        payload = json.loads(JsonLinesFormatter().format(self._record(event="app.start")))
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", payload["ts"])

    def test_unserialisable_values_do_not_break_the_writer(self) -> None:
        # A stray Path or enum must cost a type annotation, not a diagnostic.
        line = JsonLinesFormatter().format(self._record(event="app.start", where=object()))
        assert isinstance(json.loads(line)["where"], str)

    def test_exception_goes_to_the_error_field_not_the_event_field(self) -> None:
        try:
            raise RuntimeError("canary failed")
        except RuntimeError:
            import sys

            record = self._record(event=Event.RUNTIME_VERIFY_RESULT.value)
            record.exc_info = sys.exc_info()
            payload = json.loads(JsonLinesFormatter().format(record))
        assert payload["event"] == "runtime.verify.result"
        assert "canary failed" in payload["error"]


class TestLogEvent:
    def test_rejects_a_bare_string_event(self) -> None:
        with pytest.raises(TypeError, match="Event member"):
            log_event(get_logger("t"), "run.begin", case="cavity")  # type: ignore[arg-type]


class TestConfigure:
    def test_writes_json_lines_to_the_log_directory(self, tmp_path) -> None:
        logger = configure(tmp_path / "logs")
        log_event(get_logger("runtime"), Event.RUNTIME_DETECT_RESULT, state="missing")
        for handler in logger.handlers:
            handler.flush()

        lines = (tmp_path / "logs" / "foamwb.jsonl").read_text(encoding="utf-8").splitlines()
        payload = json.loads(lines[-1])
        assert payload["event"] == "runtime.detect.result"
        assert payload["state"] == "missing"
        assert payload["logger"] == "foamwb.runtime"

    def test_is_idempotent(self, tmp_path) -> None:
        # The wizard may reconfigure mid-session; that must not double every line.
        configure(tmp_path / "logs")
        logger = configure(tmp_path / "logs")
        assert len(logger.handlers) == 1

    def test_creates_the_directory(self, tmp_path) -> None:
        configure(tmp_path / "deep" / "nested" / "logs")
        assert (tmp_path / "deep" / "nested" / "logs").is_dir()
