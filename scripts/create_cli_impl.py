"""Script to create _cli_impl.py from cli.py by stripping Typer app/decorators."""

with open("distill/cli.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

skip_lines = set()

# Find and mark ALL decorator lines for removal
for i, line in enumerate(lines):
    stripped = line.strip()
    if (
        stripped.startswith("@app.command(")
        or stripped.startswith("@topic_app.command(")
        or stripped.startswith("@app.callback()")
        or stripped.startswith("@watch_app.command(")
        or stripped.startswith("@watch_app.callback()")
        or stripped.startswith("@topic_watch_app.command(")
        or stripped.startswith("@topic_watch_app.callback()")
    ):
        skip_lines.add(i)

# Find and mark ALL Typer app creation blocks and add_typer calls
in_block = False
paren_depth = 0
for i, line in enumerate(lines):
    stripped = line.strip()
    if (
        stripped.startswith("app = typer.Typer(")
        or stripped.startswith("topic_app = typer.Typer(")
        or stripped.startswith("watch_app = typer.Typer(")
        or stripped.startswith("topic_watch_app = typer.Typer(")
    ):
        in_block = True
        paren_depth = 0
    if in_block:
        paren_depth += line.count("(") - line.count(")")
        skip_lines.add(i)
        if paren_depth <= 0:
            in_block = False
    if stripped.startswith("app.add_typer("):
        skip_lines.add(i)

# Write _cli_impl.py
new_lines = []
for i, line in enumerate(lines):
    if i in skip_lines:
        continue
    new_lines.append(line)

# Update the module docstring (first line)
docstring = '''"""CLI implementation functions -- extracted from cli.py during 0.3 -> 0.4 restructure.

All command functions live here. Command registration happens in distill/commands/*.py.
The thin distill/cli.py wires everything together.
"""
'''

# Find the end of the original docstring
docstring_end = 0
if new_lines[0].strip().startswith('"""'):
    # Single-line or multi-line docstring
    if new_lines[0].strip().endswith('"""') and len(new_lines[0].strip()) > 3:
        docstring_end = 1
    else:
        for j in range(1, len(new_lines)):
            if '"""' in new_lines[j]:
                docstring_end = j + 1
                break

# Replace the docstring
result_lines = docstring.splitlines(keepends=True) + new_lines[docstring_end:]

with open("distill/_cli_impl.py", "w", encoding="utf-8") as f:
    f.writelines(result_lines)

print(f"Wrote _cli_impl.py with {len(result_lines)} lines (removed {len(skip_lines)} decorator/app lines)")
print(f"Original: {len(lines)} lines")
