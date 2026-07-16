from pathlib import Path
import py_compile
p = Path("/home/ufonik/Documents/Coding Projects/EntropicMem/skills/entropicmem/scripts/entropicmem.py")
t = p.read_text(encoding="utf-8")
bad = '        print("Usage: entropicmem recall "<q>"\n  entropicmem memory project|stats|list|list", file=sys.stderr)'
good = '        print("Usage: entropicmem memory project|stats|list", file=sys.stderr)'
if bad in t:
    t = t.replace(bad, good)
else:
    # fallback line-by-line fix around cmd_memory else
    lines = t.splitlines()
    out = []
    i = 0
    while i < len(lines):
        if lines[i].strip().startswith('print("Usage: entropicmem recall'):
            out.append('        print("Usage: entropicmem memory project|stats|list", file=sys.stderr)')
            while i < len(lines) and "file=sys.stderr)" not in lines[i]:
                i += 1
        else:
            out.append(lines[i])
        i += 1
    t = "\n".join(out) + "\n"
p.write_text(t, encoding="utf-8")
py_compile.compile(str(p), doraise=True)
print("OK")