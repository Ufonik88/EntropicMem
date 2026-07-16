import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".hermes" / "hermes-agent"))
from plugins.memory import discover_memory_providers, load_memory_provider

names = [x[0] for x in discover_memory_providers()]
print("providers:", names)
assert "entropicmem" in names, "entropicmem not discovered"
p = load_memory_provider("entropicmem")
print("name", p.name, "available", p.is_available())
p.initialize("test-session", hermes_home=str(Path.home() / ".hermes"))
print("tools", [t["name"] for t in p.get_tool_schemas()])
block = p.prefetch("budget")
print("prefetch_len", len(block))
print("OK")