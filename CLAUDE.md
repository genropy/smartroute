# Claude Code Instructions - SmartRoute

## Project Context

**SmartRoute** is an instance-scoped routing engine for Python that enables hierarchical handler organization, per-instance plugin application, and complex service composition through descriptors.

### Current Status
- **Development Status**: Beta (`Development Status :: 4 - Beta`)
- **Version**: 0.7.1
- **Has Implementation**: Yes (core complete with 100% test coverage)
- **Coverage**: 100% (82 comprehensive tests, 945 statements)
- **Plugin System**: Built-in registry with LoggingPlugin and PydanticPlugin; scope/channel via SmartPublisher's PublishPlugin
- **SmartAsync Integration**: Optional via `get(..., use_smartasync=True)`

### Project Overview

SmartRoute provides a clean, Pythonic API for:
- **Instance-Scoped Routers**: Each object gets isolated router with dedicated plugin state
- **Hierarchical Routing**: Native support for child routers and dotted path resolution (`root.api.get("users.list")`)
- **Composable Plugins**: `on_decore`/`wrap_handler` hooks with automatic propagation along router chains
- **Explicit Annotations**: `@route("router_name")` decorator with `RoutedClass` mixin for automatic finalization

**Key Dependencies**:
- `smartseeds>=0.2.0` - Smart options and kwargs extraction

The library is designed for organizing complex application routing with clean separation of concerns and plugin-based extensibility.

## Repository Information

- **Owner**: genropy
- **Repository**: https://github.com/genropy/smartroute
- **Documentation**: https://smartroute.readthedocs.io
- **License**: MIT

## Project Structure

```
smartroute/
   .github/workflows/        # CI/CD pipelines
      test.yml              # Test workflow
      docs.yml              # Documentation build
      publish.yml           # PyPI publishing via Trusted Publisher
   docs/                     # Sphinx documentation
      conf.py               # Sphinx configuration
      index.md              # Documentation index
      quickstart.md         # Quick start guide
      FAQ.md                # Frequently asked questions
      ARCHITECTURE.md       # Architecture documentation
      guide/                # User guides
         basic-usage.md
         plugins.md
         plugin-configuration.md
         hierarchies.md
         best-practices.md
      api/                  # API reference
         reference.md
         plugins.md
   src/smartroute/
      __init__.py           # Package exports
      core/
         __init__.py        # Core exports
         router.py          # Router implementation
         base_router.py     # BaseRouter class
         decorators.py      # @route, @routers decorators
         routed.py          # RoutedClass mixin
      plugins/
          __init__.py
          _base_plugin.py   # BasePlugin class
          logging.py        # LoggingPlugin
          pydantic.py       # PydanticPlugin
   tests/                   # Test suite (82 tests, 100% coverage)
      conftest.py           # Test fixtures
      test_switcher_basic.py
      test_plugins_new.py
      test_pydantic_plugin.py
      test_router_edge_cases.py
      test_router_filters_and_validation.py
      test_router_runtime_extras.py
   llm-docs/                # LLM-optimized documentation
      README.md
      API-DETAILS.md
      PATTERNS.md
   examples/                # Example implementations
   temp/                    # Temporary files (git-ignored)
   pyproject.toml           # Project configuration
   LICENSE                  # MIT License
   README.md                # Project README
   CLAUDE.md                # This file
```

## Language Policy

- **Code, comments, and commit messages**: English
- **Documentation**: English (primary)
- **Communication with user**: Italian (per user preference)

## Git Commit Policy

- **NEVER** include Claude as co-author in commits
- **ALWAYS** remove "Co-Authored-By: Claude <noreply@anthropic.com>" line
- Use conventional commit messages following project style

## Temporary Files Policy

- All temporary files MUST be in `temp/` directory
- `temp/.gitignore` ignores all files except itself
- Never commit temporary files to repository

## Documentation Standards

**SmartRoute follows Genro-Libs documentation standards:**

- **Test-First Documentation**: `$GENRO_HOME/.genro/standards/documentation-standards.md`
- **All projects use Sphinx** (not MkDocs)

**Key Requirements**:
- All docs must be derived from tests (no hallucination)
- Use Sphinx with Read the Docs theme
- MyST parser for Markdown support
- Mermaid diagrams for architecture visualization
- Test anchors linking docs to test files

## Development Guidelines

### Core Principles

1. **Instance isolation**: Every object has independent router state and plugins
2. **Minimal dependencies**: Only smartseeds from Genro-Libs ecosystem
3. **Test thoroughly**: Maintain 95%+ coverage (current: 100%)
4. **Document clearly**: Every feature derived from tests
5. **Plugin composability**: Plugins propagate automatically through child routers

### Testing

```bash
# Run tests with coverage
PYTHONPATH=src pytest --cov=src/smartroute --cov-report=term-missing

# Expected: 85/85 tests passed, 100% coverage (969 statements)
```

### Linting

```bash
# Check code style
ruff check src/smartroute/
black --check src/smartroute/
mypy src/smartroute/
```

### Documentation

```bash
# Build docs locally
sphinx-build -b html docs docs/_build/html

# Serve docs for preview
sphinx-autobuild docs docs/_build/html
```

## CI/CD Setup

**Configured and Active**:
- ✅ GitHub Actions workflows (test.yml, docs.yml, publish.yml)
- ✅ Codecov integration
- ✅ Read the Docs configuration (.readthedocs.yaml)
- ✅ PyPI trusted publisher setup

## Project Status

**v0.7.1 Beta** - Ready for release

### Completed
- [x] Core router implementation with 100% test coverage
- [x] Plugin system with logging and pydantic plugins
- [x] Hierarchical routing with attach/detach instance
- [x] Runtime plugin configuration system
- [x] Complete Sphinx documentation
- [x] GitHub Actions CI/CD
- [x] PyPI publishing via Trusted Publisher
- [x] Read the Docs integration

### Future Enhancements
- [ ] Additional plugins (async, storage, audit)
- [ ] Advanced child discovery patterns
- [ ] Performance optimization and benchmarks

## Release Process

When ready to release:

1. **Update version**:
   - `pyproject.toml` → `version = "x.y.z"`
   - `src/smartroute/__init__.py` → `__version__ = "x.y.z"`

2. **Verify tests and docs**:
   ```bash
   PYTHONPATH=src pytest --cov=src/smartroute
   sphinx-build -b html docs docs/_build/html
   ```

3. **Create and push tag**:
   ```bash
   git tag -a vx.y.z -m "Release x.y.z"
   git push origin vx.y.z
   ```

4. **GitHub Actions will automatically**:
   - Run tests on multiple OS/Python versions
   - Build package
   - Publish to PyPI via Trusted Publisher
   - Create GitHub Release with notes

## Performance Characteristics

- **Instance overhead**: Minimal (one router per object)
- **Plugin overhead**: Per-instance, no global locking
- **Child traversal**: Stack-based with cycle detection
- **Good for**: Complex application routing with plugin composition
- **Optimizations applied**:
  - Plugin specs stored as factories, instantiated once per router
  - Weakref-free design for simpler memory management

## Mistakes to Avoid

❌ **DON'T**:
- Add external dependencies beyond smartseeds
- Commit temporary files outside `temp/`
- Include Claude as co-author in commits
- Break compatibility without migration guide
- Skip tests when adding features
- Use MkDocs (Genro-Libs uses Sphinx only)

✅ **DO**:
- Keep core library minimal
- Put temporary work files in `temp/`
- Maintain high test coverage (95%+)
- Document all public APIs from tests
- Follow semantic versioning
- Use Sphinx for all documentation

---

**Author**: Genropy Team <softwell@softwell.it>
**License**: MIT
**Python**: 3.10+
