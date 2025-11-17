# SmartRoute - Next Steps

## Contesto attuale (Nov 2025)
- SmartSwitch originario verrà dismesso: la nuova implementazione vive nel repo `smartroute` (package `src/smartroute`).
- Il core è già quello “instance-scoped” (SwitchClass + descriptor) portato da `src_new/smartswitch_new`.
- Plugin attivi: logging e pydantic (duplicati in `src/smartroute/plugins`).
- Test importati da `tests/test_core_new` sono ora sotto `smartroute/tests` e passano (`PYTHONPATH=src pytest --no-cov`).
- Gli esempi (skeleton) sono in `examples/core_new_skeleton.py`.

## Decisioni prese
1. **Ridenominazione**: il progetto evoluto si chiama “SmartRoute”; vogliamo comunicare un routing engine gerarchico, non più un semplice “switch”.
2. **Architettura**: ogni classe dichiara gli switcher come attributi (`SwitchClass`). I plugin vengono istanziati per ogni oggetto, con supporto alle mappe di activation/runtime via contextvars.
3. **Documentazione**: conviene riscriverla da zero (MkDocs già impostato), includendo focus su routing, binding automatico, plugin per istanza, esempi pratici.
4. **Compatibilità**: non ci sono utenti finali, quindi non servono layer di compat; l’obiettivo è raggiungere parità funzionale con il vecchio SmartSwitch e poi eliminarlo.

## To-do (ordine suggerito)
1. **Core parity completa**
   - Verificare tutte le feature del vecchio core (`get()` options, child scanning complesso, smartasync, fallback handler, ecc.).
   - Aggiungere eventuali decorator avanzati (se servono alias multipli, custom matcher, ecc.).
2. **Plugin parity**
   - Valutare se servono altri plugin oltre a logging/pydantic (es. smartasync wrapper dedicato, storage plugin, ecc.).
   - Portare eventuali configurazioni/documentazione specifiche.
3. **Test suite completa**
   - Copiare/riscrivere i test restanti dal repo originale (config API, error cases, multi-threading, weakref, ecc.).
   - Integrare i test in `smartroute/tests` e mantenere `PYTHONPATH=src pytest` come comando canonico.
4. **Documentazione**
   - Aggiornare README + docs (MkDocs) per raccontare il nuovo modello.
   - Spiegare differenze rispetto a SmartSwitch storico e motivazioni del rename.
5. **Benchmark & Cutover**
   - Confrontare performance SmartSwitch vs SmartRoute (eventuale script benchmark).
   - Una volta pronta la doc/test, archiviare il vecchio repo o indicare SmartRoute come successore ufficiale.

> Nota: questa lista va aggiornata man mano che si chiudono i punti (basta modificare questo file).
