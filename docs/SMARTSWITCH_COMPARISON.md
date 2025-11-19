SmartSwitch vs SmartRoute
=========================

Questo documento confronta **SmartSwitch** (branch `main` del repo originale) con **SmartRoute**, coprendo parità funzionale, differenze progettuali, solidità percepita, considerazioni prestazionali e una guida di migrazione.

Panoramica
----------

| Aspetto                     | SmartSwitch (legacy)                                  | SmartRoute (nuovo)                                                       |
| --------------------------- | ----------------------------------------------------- | ------------------------------------------------------------------------ |
| Architettura               | Switcher per classe, stato condiviso tra le istanze   | Router istanziato a runtime in `__init__` per ogni oggetto               |
| Plugin                     | Global registry + ereditarietà opzionale              | Plugin per istanza con registry globale e propagazione automatica        |
| Child discovery            | `add_child` con scansione oggetti (Switchers)         | `add_child` con Router runtime, mapping/iterable e recursion controllata |
| Decorator                  | `@switch` + `switchers()`                             | `@route` + `routers()`                                                   |
| Compat layer               | API storica (SwitchClass/Switcher)                    | Terminologia nuova (Router) e nessuna compatibilità implicita           |
| Dipendenze                 | Basato su `smartswitch.core`                          | Core completamente autonomo                                              |
| Test copertura             | Alta ma distribuita su molte varianti                 | ~98% statement coverage (Pytest)                                         |
| Plugin built-in            | Logging, Pydantic                                     | Logging e Pydantic (registry interno)                                    |

Parità e differenze funzionali
------------------------------

### Caratteristiche già equivalenti

- Decorator per registrare metodi con nomi espliciti/prefix.
- Recupero handler via `get()`/`__getitem__`, default handler e opzione SmartAsync (senza plugin dedicato).
- Plugin hook `on_decore` / `wrap_handler`.
- Gestione children e path puntati (`root.api.get("child.method")`).
- Plugin logging e Pydantic riprodotti.
- Runtime data e toggle per plugin (enable/disable per handler).
- Test suite portata e ampliata (basic + edge cases).

### Differenze attuali

- **Scope dei plugin**: SmartSwitch supportava ereditarietà esplicita; SmartRoute eredita automaticamente quando si attacca un child router.
- **Registrazione globale**: SmartSwitch aveva `register_plugin` e referenze per stringa; SmartRoute ora espone un registry interno.
- **API pubblica**: SmartRoute espone solo `Router`, `route`, `RoutedClass` e si affida a nomi espliciti (nessun alias tipo Switcher).
- **Child discovery**: SmartRoute accetta Router runtime e collection (dict/list) già pronti, ma non tenta di riusare switcher non finalizzati come avveniva in alcune parti legacy.
- **Documentazione**: SmartSwitch possiede doc dettagliata (guide, reference); SmartRoute ha README e skeleton, manca la documentazione estesa.
- **Compatibilità SmartPublisher**: Non ancora verificata; eventuali script/pipeline che si aspettano `Switcher` potrebbero fallire.

Solidità e maturità
-------------------

- **SmartSwitch**: battle-tested, molte feature edge-case, plugin library ampia; tuttavia porta technical debt (global state, fallback compat).
- **SmartRoute**: codice compatto, coverage elevata, dipendenze ridotte. Ancora giovane: mancano benchmark pubblici, doc completa, plugin extra.

Prestazioni
-----------

- Non esiste un benchmark ufficiale. Aspettative:
  - **Binding**: SmartRoute effettua binding una volta per istanza; minore overhead per call successive (nessun rientro su global registry).
  - **Plugin**: per istanza, quindi leggermente più memoria ma meno lock/sharing.
  - **Child traversal**: implementato via stack + set di `id`; dovrebbe mantenere complessità in linea con SmartSwitch, ma richiede conferma tramite benchmark.

Feature mancanti rispetto a SmartSwitch
---------------------------------------

1. Ereditarietà dei plugin dal parent **parzialmente**: oggi i plugin del router padre vengono clonati sui figli al momento dell'attach, ma manca un'API esplicita tipo `use_parent_plugins()` per condividere lo stesso stack dinamicamente.
2. Plugin extra (es. storage, audit, integrazioni SmartPublisher).
3. CLI/integrazione SmartPublisher documentata.
4. Documentazione estesa (Sphinx) e tutorial.

Feature nuove o migliorate in SmartRoute
----------------------------------------

1. **Instance isolation**: ogni oggetto ha plugin/config indipendenti.
2. **Child discovery su strutture arbitrarie**: supporto nativo a dict/list/tuple con override di nome.
3. **Core modulare**: router, decorator e base plugin separati, senza retaggi SmartSwitch.
4. **Plugin registry moderno**: import automatico dei plugin built-in e possibilità di registrarne di custom obbligatoriamente.
5. **Coverage elevata**: suite Pytest con edge-case per plugin e router.
6. **Terminologia allineata**: comunicazione orientata a routing engine, non più “switch”.

Guida alla migrazione
---------------------

1. **Aggiorna import**:
   - `from smartswitch.core import Switcher` → `from smartroute.core import Router`.
   - `@switch("api")` → `@route("api")`.
   - `class Service(SwitchClass)` → `class Service(RoutedClass)`.

2. **Plugin**:
   - Per plugin personalizzati, sostituisci `switch` con `router` nei parametri e assicurati che `BasePlugin` venga importato da `smartroute.core`.
   - Se usavi plugin registrati per stringa, istanziali esplicitamente o aggiungi un piccolo factory locale.

3. **Child management**:
   - Se stavi passando direttamente `Switcher` come descriptor, ora devi istanziare il router nell’`__init__` e passare l’istanza del servizio (che contiene il relativo `Router`).
   - Usa mapping/iterable per nominare i children quando necessario.

4. **Runtime options**:
   - `get(..., use_smartasync=True)` funziona come prima, ma assicurati che `smartasync` sia installato nel nuovo ambiente.

5. **Test**:
   - Porta le suite Pytest esistenti e verifica la copertura con `PYTHONPATH=src pytest --cov=src/smartroute`.

6. **Documentazione/Script**:
   - Aggiorna README, CLI e automation per riflettere i nuovi nomi e il fatto che non esista un registry globale.

Raccomandazioni
---------------

- Avviare un piccolo progetto pilota migrando un servizio reale: validate plugin custom, child tree e performance.
- Preparare eventuali helper (`register_plugin`, `use_parent_plugins`) se i team ne sentono la mancanza.
- Pianificare benchmark e doc ufficiale prima di dichiarare SmartRoute come successore stabile.
