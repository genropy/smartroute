# Release Guide - SmartRoute

Guida per configurare Trusted Publisher e pubblicare su PyPI.

## ✅ Completato

- [x] Workflow `.github/workflows/publish.yml` creato
- [x] Workflow `.github/workflows/docs.yml` creato

## 📋 Prossimi Step

### 1. Configurare Trusted Publisher su PyPI

**Vai su**: https://pypi.org/manage/account/publishing/

1. **Login** su PyPI
2. **Add a new pending publisher**:
   - **PyPI Project Name**: `smartroute`
   - **Owner**: `genropy` (o il nome dell'organizzazione GitHub)
   - **Repository name**: `smartroute`
   - **Workflow name**: `publish.yml`
   - **Environment name**: `release`
3. **Save**

### 2. Commit e Push Workflow

```bash
# Commit e push dei workflow
git add .github/workflows/ RELEASE.md
git commit -m "ci: add publish and docs workflows for PyPI Trusted Publisher"
git push origin main
```

### 3. Release su PyPI

```bash
# Creare tag stable (senza rc/alpha/beta)
git tag v0.1.0
git push origin v0.1.0
```

**Cosa succede**:
- GitHub Actions si attiva sul tag
- Workflow `publish.yml` builds il package
- Pubblica su PyPI (solo tag stabili, senza rc/alpha/beta)
- Crea GitHub Release automaticamente con note generate

**Verificare**:
- Check workflow: https://github.com/genropy/smartroute/actions
- Check package: https://pypi.org/project/smartroute/
- Check release: https://github.com/genropy/smartroute/releases

**Installare**:
```bash
pip install smartroute
```

## 📝 Note Importanti

### Tag Naming Convention

- **Releases**: `v0.1.0`, `v1.0.0`, `v2.1.3`
  - Pubblica su **PyPI**
  - Crea **GitHub Release** automaticamente

### Trusted Publisher vs Token

**✅ Trusted Publisher (raccomandato)**:
- No secrets da configurare
- Sicuro (OIDC authentication)
- Configurazione one-time su PyPI

**❌ Token (non usare)**:
- Richiede `PYPI_API_TOKEN` secret
- Meno sicuro
- Non conforme agli standard Genro

### Workflow Features

- **Auto-build**: Package built automaticamente
- **Auto-publish**: Upload automatico su PyPI/TestPyPI
- **GitHub Release**: Creata automaticamente per stable releases
- **Artifacts**: Distribution files disponibili come artifacts

### Troubleshooting

**Errore: "Package already exists"**
- TestPyPI: Non puoi ri-uploadare lo stesso numero di versione
- Soluzione: Incrementa versione in `pyproject.toml`

**Errore: "Trusted publisher not configured"**
- Verifica configurazione su PyPI/TestPyPI
- Owner, repo, workflow name, environment devono matchare esattamente

**Workflow non parte**
- Verifica che il tag inizi con `v`
- Check logs: https://github.com/genropy/smartroute/actions

## 🔄 Workflow per Nuove Release

1. **Aggiorna versione** in `pyproject.toml`
2. **Commit e push** su main
3. **Crea tag** (tag `vX.Y.Z`)
4. **Push tag** - il workflow farà tutto automaticamente (build, publish, GitHub release)

## 📚 Riferimenti

- Trusted Publisher: https://docs.pypi.org/trusted-publishers/
- GitHub Actions: https://docs.github.com/actions
- PyPI: https://pypi.org/
- TestPyPI: https://test.pypi.org/
