SmartRoute
==========

[![Tests](https://github.com/genropy/smartroute/actions/workflows/test.yml/badge.svg)](https://github.com/genropy/smartroute/actions/workflows/test.yml)
[![codecov](https://codecov.io/gh/genropy/smartroute/branch/main/graph/badge.svg?token=71c0b591-018b-41cb-9fd2-dc627d14a519)](https://codecov.io/gh/genropy/smartroute)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

SmartRoute è il successore instance-scoped di SmartSwitch: un *routing engine* per Python che consente di organizzare handler gerarchici, applicare plugin per istanza e comporre servizi complessi tramite descrittori.

Caratteristiche principali
--------------------------

- **Router per istanza** – ogni oggetto ottiene un `BoundRouter` isolato, con stato dei plugin e configurazioni dedicate.
- **Gerarchie annidate** – supporto nativo a child routers, path puntati (`root.api.get("users.list")`) e scansione automatica di oggetti/collezioni.
- **Plugin composabili & ereditabili** – hook `on_decore`/`wrap_handler`, registry globale, auto-registrazione dei plugin built-in e propagazione automatica lungo le catene di router.
- **Annotazioni esplicite** – decorator `@route("router_name")` registra i metodi; il mixin `RoutedClass` finalizza automaticamente i router definiti sulla classe.
- **Compatta ma estendibile** – core senza dipendenze da SmartSwitch, copertura test >95%, codice pronto per essere documentato/esteso.

Limitazioni attuali
-------------------

- Solo metodi di istanza: i router assumono che le funzioni registrate siano bound methods (nessun supporto a static/class method o callables libere).
- Non esiste ancora una CLI o integrazione diretta con SmartPublisher; `get(..., use_smartasync=True)` resta opzionale ma non esiste un plugin SmartAsync dedicato.
- Il sistema di plugin è volutamente minimale (no Pydantic declarative config per ora); eventuali feature avanzate vanno aggiunte manualmente.

Installazione
-------------

Clona il repository e usa `pip` con un virtualenv:

```bash
git clone https://github.com/<org>/smartroute.git
cd smartroute
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

Per usare il plugin Pydantic:

```bash
pip install -e .[pydantic]
```

Concetti base
-------------

- `Router`: descrittore usato come decorator sugli handler (`@route("router_attr")`).
- `RoutedClass`: mixin che finalizza automaticamente i router definiti sulla classe.
- `BoundRouter`: istanza runtime legata a un oggetto, con `get`, `call`, `add_child`, `iter_plugins`.
- `BasePlugin`: classe base per definire hook per istanza (`on_decore`, `wrap_handler`).
- Plugin built-in registrati automaticamente: `LoggingPlugin` e `PydanticPlugin` (utilizzabili come `router.plug("logging")`). I plugin esterni devono chiamare `Router.register_plugin("nome", PluginClass)` prima dell'uso.

Esempio rapido
--------------

```python
from smartroute.core import RoutedClass, Router, route
from smartroute.plugins.logging import LoggingPlugin

class UsersService(RoutedClass):
    api = Router(name="users").plug(LoggingPlugin())

    def __init__(self, label: str):
        self.label = label

    @route("api")
    def list(self):
        return f"{self.label}:list"

    @route("api", alias="detail")
    def get_detail(self, ident: int):
        return f"{self.label}:detail:{ident}"

svc = UsersService("customers")
handler = svc.api.get("detail")
print(handler(42))  # -> customers:detail:42
```

Router annidati e child discovery
---------------------------------

```python
class RootAPI(RoutedClass):
    api = Router(name="root")

    def __init__(self):
        self.users = UsersService("users")
        self.products = UsersService("products")
        self.api.add_child({"users": self.users, "products": self.products})

root = RootAPI()
assert root.api.get("users.list")() == "users:list"
assert root.api.get("products.detail")(5) == "products:detail:5"
```

Annotazioni di routing
----------------------

Oltre all’attributo Router, puoi usare i decorator standalone:

```python
from smartroute.core import routers, route

@routers("public_api")
class Service:
    @route("public_api")
    def ping(self):
        return "pong"
```

Testing e coverage
------------------

Il core punta a >95% di coverage (attualmente ~98%). Per riprodurre:

```bash
PYTHONPATH=src pytest --cov=src/smartroute --cov-report=term-missing
```

Struttura del repository
------------------------

- `src/smartroute/core/` – `router.py`, `decorators.py`, `base.py`.
- `src/smartroute/plugins/` – plugin logging & pydantic.
- `tests/` – suite Pytest (inclusi edge cases per router e plugin).
- `examples/` – skeleton con più router e plugin.

Prossimi passi suggeriti
------------------------

- Documentazione MkDocs con tutorial e API reference.
- Plugin aggiuntivi (async, storage, audit trail).
- Benchmark e confronto con il vecchio SmartSwitch.
