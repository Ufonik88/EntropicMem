# EntropicMem Backup & Restore

## Backup (encrypted)

A scheduled backup job runs the encryption + upload routine:

1. Tar `memory.db`, `index.db`, `vault/`
2. Encrypt with OpenSSL AES-256-CBC (pbkdf2, 200k iter) using key file `~/.hermes/entropicmem/.backup_key` (mode 600; auto-created)
3. Upload only `*.tar.gz.enc` via rclone
4. Keep last 7 local ciphertext archives; delete plaintext tars

Env:

| Var | Default |
|-----|---------|
| `HERMES_HOME` | `~/.hermes` |
| `ENTROPICMEM_BACKUP_KEY_FILE` | `$HERMES_HOME/entropicmem/.backup_key` |
| `RCLONE_REMOTE` | `your-remote` |
| `RCLONE_PATH` | `your/backup/path` |

> Set `RCLONE_REMOTE` and `RCLONE_PATH` to your own rclone remote and backup folder before running the backup job. The placeholders `your-remote` and `your/backup/path` are intentionally not real destinations.

## Restore drill

```bash
# 1. Fetch ciphertext (substitute your remote and path)
rclone copy your-remote:your/backup/path/entropicmem_YYYY-mm-dd_HHMMSS.tar.gz.enc /tmp/

# 2. Decrypt
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
  -in /tmp/entropicmem_....tar.gz.enc \
  -out /tmp/entropicmem_restore.tar.gz \
  -pass file:$HOME/.hermes/entropicmem/.backup_key

# 3. Extract to staging (never overwrite live without stop)
mkdir -p /tmp/em-restore && tar -xzf /tmp/entropicmem_restore.tar.gz -C /tmp/em-restore

# 4. Integrity
sqlite3 /tmp/em-restore/entropicmem/memory.db 'PRAGMA integrity_check;'

# 5. Cut over (stop agents first)
systemctl --user stop entropicmem-graph-server.service  # if running
# backup live, then:
# rsync -a /tmp/em-restore/entropicmem/ ~/.hermes/entropicmem/
chmod 700 ~/.hermes/entropicmem
chmod 600 ~/.hermes/entropicmem/*.db
```

## Engine snapshots (v3, `em.store.backup`)

The v3 store's own snapshots are the engine's, not this shell routine's. One
snapshot is a directory:

```
backups/
└── <reason>-<stamp>/
    ├── memory.db        # the fact store (verified, mode 0600)
    ├── index.db         # the vault index, when it exists
    └── manifest.json    # every file: role, sha256, size, counts, user_version
```

`snapshot(reason)` writes it and returns the directory; the pre-3.1 name
`create(reason)` does the same and returns the details. `verify()` re-hashes
every file and re-runs `PRAGMA integrity_check` on each one. Rotation keeps 7
routine plus 5 safety snapshots, counting this layout and the pre-3.1 flat files
(`<reason>-<stamp>.db` beside `<reason>-<stamp>.json`) in one policy; legacy
snapshots stay readable and restorable and are never rewritten.

Drill: `verify()` the snapshot you intend to restore, then `restore()` it. It
refuses a live path without `allow_live=True`, refuses while the provider holds
`<db>.lock`, refuses a snapshot that fails verification, and keeps a
`pre-restore` snapshot of what it replaces. Restore stages every file first and
swaps only when all of them verify, and it never touches an index database the
snapshot does not contain.

## Game day checklist

- [ ] Decrypt succeeds with the backup key
- [ ] `PRAGMA integrity_check` = ok
- [ ] Fact count within expected range
- [ ] Vault note sample opens
- [ ] `python3 ~/.hermes/plugins/entropicmem/scripts/entropicmem.py memory stats` OK after cutover
