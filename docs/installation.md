# Installation

## Requirements

- Python 3.10 or higher
- pip package manager

## From PyPI

```bash
pip install smartroute
```

## With Optional Dependencies

### Pydantic Plugin

For automatic argument validation using type hints:

```bash
pip install smartroute[pydantic]
```

### Development Tools

For development with all optional dependencies:

```bash
pip install smartroute[dev]
```

### All Dependencies

To install everything:

```bash
pip install smartroute[all]
```

## From Source

For development or to use the latest unreleased features:

```bash
git clone https://github.com/genropy/smartroute.git
cd smartroute
pip install -e ".[all]"
```

This installs SmartRoute in editable mode with all optional dependencies.

## Verify Installation

Test your installation:

```python
python -c "from smartroute.core import Router, RoutedClass, route; print('SmartRoute installed successfully!')"
```

## Next Steps

- [Quick Start Guide](quickstart.md) - Get started in 5 minutes
- [Basic Usage Guide](guide/basic-usage.md) - Learn the fundamentals
- [Plugin Guide](guide/plugins.md) - Extend SmartRoute with plugins
