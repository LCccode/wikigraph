"""LLM Wiki - Enterprise knowledge base with structured Wiki + knowledge graph."""

__version__ = "0.4.1"

# Lazy imports (same pattern as graphify)
_LAZY = {
    "detect": "detect",
    "convert_file": "convert",
    "extract_structure": "structure",
    "build_graph": "build",
    "cluster": "cluster",
    "analyze": "analyze",
}


def __getattr__(name: str):
    if name in _LAZY:
        module = __import__(f"lcwiki.{_LAZY[name]}", fromlist=[name])
        return getattr(module, name)
    raise AttributeError(f"module 'lcwiki' has no attribute {name}")
