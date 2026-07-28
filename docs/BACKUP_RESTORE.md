# EntropicMem Backup & Restore

## Backup (encrypted)

Daily cron runs `scripts/entropicmem_backup.sh`:

1. Tar `memory.db`, `index.db`, `vault/`
2. Encrypt with OpenSSL AES-256-CBC (pbkdf2, 200k iter) using key file  
   `~/.hermes/entropicmem/.backup_key` (mode 600; auto-created)
3. Upload **only** `*.tar.gz.enc` via rclone
4. Keep last 7 local ciphertext archives; delete plaintext tars

Env:

| Var | Default |
|-----|---------|
| `HERMES_HOME` | `~/.hermes` |
| `ENTROPICMEM_BACKUP_KEY_FILE` | `$HERMES_HOME/entropicmem/.backup_key` |
| `RCLONE_REMOTE` | `mygdrive` |
| `RCLONE_PATH` | `hermes-backups/entropicmem` |

## Restore drill

```bash
# 1. Fetch ciphertext
rclone copy mygdrive:hermes-backups/entropicmem/entropicmem_YYYY-mm-dd_HHMMSS.tar.gz.enc /tmp/

# 2. Decrypt
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000   -in /tmp/entropicmem_....tar.gz.enc   -out /tmp/entropicmem_restore.tar.gz   -pass file:$HOME/.hermes/entropicmem/.backup_key

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

## Game day checklist

- [ ] Decrypt succeeds with production key
- [ ] `PRAGMA integrity_check` = ok
- [ ] Fact count within expected range
- [ ] Vault note sample opens
- [ ] Health check OK after cutover
