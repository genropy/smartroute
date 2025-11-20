"""Plugin package initialiser.

Keep this module lightweight so it can be imported during Router start-up
without triggering the built-in plugins. Each plugin module (`logging`,
`pydantic`, `scope`) registers itself when imported explicitly (see
``smartroute.__init__``).
"""

__all__: list[str] = []
