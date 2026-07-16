# Capability Comparison (generic classes)

| Capability class | Typical approach | EntropicMem |
|------------------|----------------|-------------|
| Session-only context | Rely on chat history | `remember` + `recall` persist facts |
| Markdown wiki | Manual notes + plugins | Vault + `ingest`/`moc`/`lint` |
| Vector memory SaaS | Hosted API | Optional local semantic re-rank; core FTS stdlib |
| Agent skills | Ad-hoc scripts | Unified CLI + skill + tests |

EntropicMem is designed to cover durable memory, linked archive, retrieval, maintenance, and visualization in one installable package.
