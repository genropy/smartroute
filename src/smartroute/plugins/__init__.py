"""Plugin package initialiser (source of truth).

Rebuild rules:
- Keep this file lightweight; do not import concrete plugins here so imports of
  ``smartroute.plugins`` remain side-effect free.
- Concrete plugin modules (``logging``, ``pydantic``) self-register when
  imported elsewhere (see ``smartroute.__init__`` for eager imports).
"""

__all__: list[str] = []
