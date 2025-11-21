"""
AppRegistry - gestore runtime delle applicazioni pubblicate.

Questa versione non persiste più i metadati su disco: ogni app
registrata viene immediatamente importata, istanziata e collegata
al Publisher. Rimane attiva finché non viene esplicitamente rimossa.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

from smartroute.core import RoutedClass, Router, route


class AppRegistry(RoutedClass):
    """
    Registry runtime delle applicazioni pubblicate.

    Gli handler sono esposti su `.apps <command>`:
        - add: aggiunge (e istanzia) una nuova app
        - remove: smonta un'app attiva
        - list: restituisce le app attualmente montate
        - getapp: mostra i metadati runtime di una singola app
    """

    api = Router(name="apps").plug("pydantic")

    def __init__(self, publisher=None, **_):
        """
        Args:
            publisher: Publisher a cui collegare automaticamente le app.
        """
        super().__init__()
        self._publisher = publisher
        self.applications: dict[str, Any] = {}
        self._metadata: dict[str, dict[str, str]] = {}

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #
    def _resolve_path(self, path: str) -> Path:
        path_obj = Path(path).expanduser().resolve()
        if not path_obj.exists():
            raise FileNotFoundError(f"Path does not exist: {path_obj}")
        return path_obj

    def _ensure_import_path(self, path: Path) -> None:
        path_str = str(path)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)

    def _instantiate_app(self, path: Path, module: str, class_name: str):
        self._ensure_import_path(path)
        mod = importlib.import_module(module)
        try:
            app_class = getattr(mod, class_name)
        except AttributeError as exc:
            raise AttributeError(f"Module '{module}' has no class '{class_name}'") from exc
        return app_class()

    def _attach_to_publisher(self, name: str, app) -> None:
        if self._publisher is not None and hasattr(app, "api"):
            self._publisher.api.add_child(app.api, name=name)

        if hasattr(app, "_set_publisher") and self._publisher is not None:
            app._set_publisher(self._publisher)

        if hasattr(app, "smpub_on_add") and not getattr(app, "_smpub_on_add_called", False):
            app.smpub_on_add()
            setattr(app, "_smpub_on_add_called", True)

    def _detach_from_publisher(self, name: str, app) -> None:
        if hasattr(app, "smpub_on_remove") and not getattr(app, "_smpub_on_remove_called", False):
            app.smpub_on_remove()
            setattr(app, "_smpub_on_remove_called", True)

        if self._publisher is not None:
            try:
                self._publisher.api._children.pop(name, None)
            except AttributeError:
                pass

    # ------------------------------------------------------------------ #
    # Commands                                                           #
    # ------------------------------------------------------------------ #
    @route("api")
    def add(self, name: str, path: str, module: str = "main", class_name: str = "App") -> dict:
        """
        Registra e monta immediatamente una nuova applicazione.
        """
        if name in self.applications:
            return {"error": f"App '{name}' already registered", "name": name}

        try:
            path_obj = self._resolve_path(path)
            app = self._instantiate_app(path_obj, module, class_name)
        except (FileNotFoundError, ImportError, AttributeError) as exc:
            return {"error": str(exc), "name": name}

        self.applications[name] = app
        self._metadata[name] = {"path": str(path_obj), "module": module, "class": class_name}
        try:
            self._attach_to_publisher(name, app)
        except Exception as exc:  # pragma: no cover - propagato come errore utente
            self.applications.pop(name, None)
            self._metadata.pop(name, None)
            return {"error": str(exc), "name": name}

        return {"status": "registered", "name": name, **self._metadata[name]}

    @route("api")
    def remove(self, name: str) -> dict:
        """Smonta un'app attiva."""
        if name not in self.applications:
            return {
                "error": "App not found",
                "name": name,
                "available": list(self.applications.keys()),
            }

        app = self.applications.pop(name)
        self._detach_from_publisher(name, app)
        self._metadata.pop(name, None)

        return {"status": "removed", "name": name}

    @route("api")
    def list(self) -> dict:
        """Elenca le app attualmente montate."""
        return {"total": len(self.applications), "apps": dict(self._metadata)}

    @route("api")
    def getapp(self, name: str) -> dict:
        """Restituisce i metadati di un'app montata."""
        if name not in self.applications:
            return {
                "error": "App not found",
                "name": name,
                "available": list(self.applications.keys()),
            }

        return {"name": name, **self._metadata[name]}

    # ------------------------------------------------------------------ #
    # Runtime API                                                        #
    # ------------------------------------------------------------------ #
    def load(self, name: str):
        """
        Restituisce l'istanza runtime di un'app.

        In questa nuova versione non vengono creati nuovi oggetti qui:
        `add()` ha già istanziato l'app, quindi load() si limita a
        recuperarla oppure solleva ValueError.
        """
        if name not in self.applications:
            available = list(self.applications.keys())
            raise ValueError(
                f"App '{name}' not registered. "
                f"Available: {', '.join(available) if available else 'none'}"
            )
        return self.applications[name]

    def unload(self, name: str) -> dict:
        """Alias programmatico di remove()."""
        return self.remove(name)
