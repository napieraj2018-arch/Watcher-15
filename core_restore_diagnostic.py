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
                    or any(word in node.name.lower() for word in ("restore", "storage")))
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


def emit(manager_type):
    try:
        records = describe(manager_type)
    except Exception:
        # Exception text or repr could contain paths or private application data.
        records = [{"status": "inspection_unavailable"}]
    for record in records:
        print("AIB_CORE_FLOW " + json.dumps(record, ensure_ascii=True), flush=True)
