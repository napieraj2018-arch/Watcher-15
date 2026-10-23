"""Temporary, value-free inspection of the loaded legacy profile control flow.

Only class source is parsed. No session, environment, browser or profile values
are read. All literal values and docstrings are removed before private logging.
This does not change browser behavior or introduce an HTTP endpoint.
"""
import ast
import inspect
import json
import textwrap


class Redact(ast.NodeTransformer):
    def visit_Constant(self, node):
        return ast.copy_location(ast.Constant(value="REDACTED_LITERAL"), node)


def describe(manager_type):
    tree = ast.parse(textwrap.dedent(inspect.getsource(manager_type)))
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    if len(classes) != 1:
        return []
    records = []
    for node in classes[0].body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        original = ast.unparse(node)
        selected = (node.name in {"start", "navigate", "flush_profile", "stop"}
                    or any(word in node.name.lower() for word in ("restore", "storage", "portable_state")))
        if not selected:
            continue
        flags = {word: word in original for word in (
            "add_init_script", "localStorage", "setItem", "storage_state")}
        # Never serialize a bound object or runtime state. Even harmless static
        # strings are removed, including JS templates and default arguments.
        scrubbed = Redact().visit(node)
        ast.fix_missing_locations(scrubbed)
        body = ast.unparse(scrubbed)
        if len(body) > 12000 or len(records) >= 12:
            return [{"status": "source_exceeds_bound"}]
        records.append({"method": node.name, "flags": flags, "flow": body})
    return records


def describe_callable(fn):
    if inspect.ismethod(fn):
        fn = fn.__func__
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn.__code__)))
    flags = {word: word in ast.unparse(tree) for word in (
        "add_init_script", "localStorage", "setItem", "storage_state")}
    text = ast.unparse(Redact().visit(tree))
    if len(text) > 16000:
        return {"status": "source_exceeds_bound"}
    return {"flags": flags, "flow": text}


def emit(manager):
    try:
        records = describe(type(manager))
        # Only inspect callable source and callable closure links. Non-callable
        # cells are never serialized, traversed or represented in diagnostics.
        seen = set()
        queue = [(name, getattr(manager, name, None), 0) for name in (
            "start", "navigate", "_save_portable_state", "_load_portable_state")]
        while queue and len(seen) < 24:
            label, fn, depth = queue.pop(0)
            if inspect.ismethod(fn):
                fn = fn.__func__
            if not inspect.isfunction(fn) or id(fn) in seen:
                continue
            seen.add(id(fn))
            records.append({"binding": label, **describe_callable(fn)})
            if depth < 4:
                for name, cell in zip(fn.__code__.co_freevars, fn.__closure__ or ()):
                    value = cell.cell_contents
                    if inspect.isfunction(value) or inspect.ismethod(value):
                        queue.append((label + "." + name, value, depth + 1))
    except Exception:
        # Exception text or repr could contain paths or private application data.
        records = [{"status": "inspection_unavailable"}]
    for record in records:
        print("AIB_CORE_FLOW " + json.dumps(record, ensure_ascii=True), flush=True)
