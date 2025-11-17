"""Tests for the logging plugin."""

# Import to trigger plugin registration
import smartroute.plugins.logging  # noqa: F401
from smartroute import RoutedClass, Router, route


class LoggedService(RoutedClass):
    routes = Router(name="logged").plug("logging")

    def __init__(self):
        self.calls = 0

    @route("routes")
    def hello(self):
        self.calls += 1
        return "ok"


def test_logging_plugin_runs_per_instance(monkeypatch):
    records = []

    class DummyLogger:
        def __init__(self):
            self._handlers = True

        def has_handlers(self):
            return True

        # Compatibility alias
        hasHandlers = has_handlers  # noqa: N815

        def info(self, message):
            records.append(message)

    svc = LoggedService()
    svc.routes.logger._logger = DummyLogger()  # type: ignore[attr-defined]

    assert svc.routes.get("hello")() == "ok"
    assert svc.calls == 1
    assert records and "hello" in records[0]

    other = LoggedService()
    assert other.calls == 0
