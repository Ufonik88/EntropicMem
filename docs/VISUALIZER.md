# Visualizer

`entropicmem graph export --format html --output-dir ./export`

- Single self-contained `graph.html` (D3 v7, dark theme)
- Nodes = vault notes; edges = wikilinks
- Filters: `--domain`, `--max-nodes`, `--min-importance`
- Serve: `entropicmem graph serve --port 8080 --dir ./export`
