# Ticket: Extend SmartRoute `describe()` to expose runtime handlers

## Background
In SmartRoute, `Router.describe()` currently returns a purely descriptive schema:

```python
def describe(self) -> Dict[str, Any]:
    def describe_node(node: "BoundRouter") -> Dict[str, Any]:
        return {
            "name": node.name,
            "prefix": node.prefix,
            "plugins": [...],
            "methods": {...},
            "children": {key: describe_node(child) for key, child in node._children.items()},
        }
```

This is useful for documentation/help, but it does **not** expose the runtime handler instances or bound callables. Frameworks like `smartpublisher` need those references to actually invoke methods (CLI/HTTP dispatch), so they maintain a parallel map (`published_instances`) alongside the router tree.

## Issue
- `describe()` omits the object references: `children["apps"]` is just a dict, not the `AppRegistry` instance.
- Even when handlers are published dynamically after `PublishedClass.__init__`, `describe()` must be called again to see them, and it still produces only descriptive dicts.
- As a result, consumers cannot rely on `describe()` as the single source of truth for both schema and runtime invocation.

## Proposal
Add a capability to SmartRoute (either via a new flag or via a companion API) that returns runtime-aware data:

- Option A: `Router.describe(runtime=True)` includes, for each child, a lightweight handle (e.g., an object id or callable) so frameworks can recover the actual handler.
- Option B: expose a new method (e.g., `Router.inspect()`) that yields `(name, instance, schema)` tuples, merging the current descriptive info with the bound handler.

This would allow frameworks to drop custom registries (`published_instances`) and use the router itself as the single source of truth.

## Benefits
- Simplifies consumers (no dual bookkeeping).
- Reduces the risk of desynchronizing router and runtime maps.
- Keeps the current `describe()` behavior for documentation (when `runtime=False` or unspecified), preserving backward compatibility.

## Next steps
1. Discuss API shape (flag vs new method) with SmartRoute maintainers.
2. Implement the runtime-aware mode and update docs/tests in SmartRoute.
3. Update smartpublisher to leverage the new capability once available.
