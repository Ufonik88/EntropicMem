# Vault Schema

## Layout
```
vault/
├── AGENTS.md, SCHEMA.md, index.md, log.md, Wiki-Cache.md
├── inbox/, .raw/, templates/, attachments/, _archive/
└── <Domain>/*.md
```

## Note types
`literature`, `permanent`, `moc`, `index`, `log`

## Frontmatter
See seed `SCHEMA.md` in vault. Required: `title`, `type`, `tags`, `created`, `source`, `domain`, `entropic_id` (when from `remember`).

## Wikilinks
`[[Note Title]]` or `[[Domain/Note Title]]` — case-sensitive on Linux.
