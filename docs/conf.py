"""Sphinx configuration for SmartRoute documentation."""
import os
import sys
from pathlib import Path

# Add source directory to path for autodoc
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Project information
project = "SmartRoute"
copyright = "2025, Genropy Team"
author = "Genropy Team"
release = "0.2.0"
version = "0.2"

# General configuration
extensions = [
    "sphinx.ext.autodoc",           # Auto-generate docs from docstrings
    "sphinx.ext.napoleon",          # Google/NumPy style docstrings
    "sphinx.ext.viewcode",          # Add links to source code
    "sphinx.ext.intersphinx",       # Link to other projects' docs
    "sphinx.ext.todo",              # TODO notes support
    "sphinx.ext.coverage",          # Coverage reporting
    "sphinx.ext.githubpages",       # GitHub Pages support
    "sphinx_autodoc_typehints",     # Type hints in docs
    "myst_parser",                  # Markdown support (CRITICAL)
    "sphinxcontrib.mermaid",        # Mermaid diagrams (CRITICAL)
]

# MyST Parser configuration (Markdown)
myst_enable_extensions = [
    "colon_fence",      # ::: fences
    "deflist",          # Definition lists
    "substitution",     # Variable substitutions
    "tasklist",         # Task lists with checkboxes
]
myst_heading_anchors = 3

# CRITICAL: Treat ```mermaid blocks as mermaid directives
myst_fence_as_directive = ["mermaid"]

# Source files
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

# The master toctree document
master_doc = "index"

# Patterns to ignore
exclude_patterns = [
    "_build",
    "Thumbs.db",
    ".DS_Store",
    "dev-notes",
    "temp",
]

# Suppress specific warnings
suppress_warnings = [
    "toc.not_included",              # Docs not in toctree
    "myst.xref_missing",             # Missing cross-references
    "misc.highlighting_failure",     # Pygments highlighting issues
]

# HTML output configuration
html_theme = "sphinx_rtd_theme"
html_theme_options = {
    "navigation_depth": 4,
    "collapse_navigation": False,
    "sticky_navigation": True,
    "includehidden": True,
    "titles_only": False,
    "prev_next_buttons_location": "bottom",
    "style_external_links": True,
}

html_static_path = []  # No static files yet
html_css_files = []    # No custom CSS yet

# HTML context (GitHub integration)
html_context = {
    "display_github": True,
    "github_user": "genropy",
    "github_repo": "smartroute",
    "github_version": "main",
    "conf_py_path": "/docs/",
}

# Autodoc configuration
autodoc_default_options = {
    "members": True,
    "member-order": "bysource",
    "special-members": "__init__",
    "undoc-members": True,
    "exclude-members": "__weakref__",
}
autodoc_typehints = "description"
autodoc_typehints_description_target = "documented"

# Napoleon settings (Google-style docstrings)
napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = True
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True
napoleon_use_admonition_for_examples = True
napoleon_use_admonition_for_notes = True
napoleon_use_admonition_for_references = False
napoleon_use_ivar = False
napoleon_use_param = True
napoleon_use_rtype = True
napoleon_preprocess_types = True
napoleon_type_aliases = None
napoleon_attr_annotations = True

# Intersphinx configuration
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pydantic": ("https://docs.pydantic.dev/latest/", None),
}

# Todo extension configuration
todo_include_todos = True

# Type hints configuration
typehints_fully_qualified = False
always_document_param_types = True
typehints_document_rtype = True
