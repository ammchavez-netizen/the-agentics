**Edited Troubleshooting Brief – Apache HTTPS fails after installing a self‑signed certificate (RHEL 9)**  

---

### 1. Symptoms (what the client sees)

| Symptom | Typical client output |
|---------|-----------------------|
| `https://<hostname>` request | *SSL handshake failure* (e.g. `SSL_ERROR_SYSCALL`, `SSL handshake failed`) **or** *connection timed out* |
| `systemctl status httpd` after reload | `active (running)` – no start‑up errors reported |
| Server‑side logs (initially) | May be empty or contain only generic messages; no obvious “file not found” errors |

> **Note:** A clean Apache start only proves that the configuration syntax is valid; it does **not** guarantee that the TLS engine could actually load the certificate.

---

### 2. Likely root‑cause categories  

| Category | Why it can produce the observed symptom |
|----------|------------------------------------------|
| **SELinux denial** – certificate/key lack the `httpd_config_t` (or `httpd_sys_content_t`) label while SELinux is in *enforcing* mode. Apache’s `httpd_t` domain is blocked from reading the files, so the SSL library cannot initialise the certificate and the handshake aborts. |
| **Network‑level block** – firewall (`firewalld`/iptables) or external ACL does not allow inbound TCP 443, or the port is not actually listening after the Apache reload. |
| **Apache listen / VirtualHost mis‑configuration** – missing `Listen 443` or `<VirtualHost *:443>` block, causing Apache to drop the connection. |
| **File‑permission / ownership mismatch** – key owned by a user other than `root` or permissions too restrictive; SELinux will still block even if Unix perms look correct. |
| **Certificate format problems** – file is not PEM‑encoded, the private key is encrypted with a passphrase, or the cert and key do not match. This typically shows up as `AH01909: SSL library error` in the error log. |

> The original brief presented SELinux as the *sole* cause. In practice any of the above categories (or a combination) can be responsible, so the diagnostic flow checks each one.

---

### 3. Diagnostic checklist (commands run as **root**)

| Step | Command | Expected result | What it proves |
|------|---------|-----------------|----------------|
| **3.1 Verify Apache is listening on 443** | `ss -tlnp | grep ':443'` | `LISTEN 0 128 *:443 *:* users:(("httpd",pid=xxxx,fd=xx))` | Confirms the daemon is bound to the HTTPS port. |
| **3.2 Confirm local firewall permits 443** | `firewall-cmd --zone=public --list-all`  <br>or `iptables -S` | `ports: 443/tcp` **or** a rule `-A INPUT -p tcp -m tcp --dport 443 -j ACCEPT` | Shows inbound traffic is not blocked locally. |
| **3.3 Verify external network ACLs** | (Ask network team / review cloud security‑group rules) | Port 443 allowed from client IP range | Rules outside the host are not silently dropping packets. |
| **3.4 Look for SELinux denials** | `ausearch -m avc -ts recent | audit2allow -w`  <br>or `grep -i denied /var/log/audit/audit.log` | Lines containing `type=AVC` with `httpd_t` trying to read the cert/key | Direct evidence SELinux is preventing access. |
| **3.5 Check SELinux context of cert & key** | `ls -Z /path/to/cert.crt /path/to/key.key` | `system_u:object_r:httpd_config_t:s0` (or `httpd_sys_content_t`) for **both** files | Correct label required for Apache to read them. |
| **3.6 Scan Apache error log for SSL‑related messages** | `tail -n 30 /var/log/httpd/error_log` | Entries such as `AH01909: SSL library error`, `Permission denied`, or `SSL: error:...` | Helps differentiate SELinux from other SSL initialisation failures. |
| **3.7 Validate certificate & key format** | `openssl x509 -in /path/to/cert.crt -noout -text`  <br>`openssl rsa -in /path/to/key.key -check -noout` | Human‑readable certificate details; “RSA key ok” (no “ENCRYPTED” line) | Confirms PEM format and that the private key is **not** encrypted with a passphrase. |
| **3.8 Verify mod_ssl is loaded** | `httpd -M | grep ssl` | `ssl_module (shared)` | Guarantees the SSL module is active. |
| **3.9 Test the TLS handshake directly** | `openssl s_client -connect <hostname>:443 -servername <hostname> -tls1_2 -brief` | Handshake succeeds, shows certificate chain (or at least “SSL handshake has read …”) | Gives a low‑level view of what the client sees. |

**Safety note:** All commands above are read‑only except those that modify the firewall or SELinux policy (see Section 4). Run them first; only proceed to remediation if a problem is confirmed.

---

### 4. Remediation (ordered by invasiveness)

#### 4.1 Relabel certificate and key for SELinux  

```bash
# 1. Restore default SELinux context for the standard directory tree (safe – only changes labels)
restorecon -Rv /etc/pki/tls

# 2. If the files live outside the default tree, add a custom fcontext rule (requires semanage)
semanage fcontext -a -t httpd_config_t "/custom/path/.*\.crt"
semanage fcontext -a -t httpd_config_t "/custom/path/.*\.key"

# 3. Apply the new context to the specific files
restorecon -v /custom/path/yourcert.crt /custom/path/yourkey.key
```

*Impact:* No file contents are altered; only SELinux labels change. No service restart required for the label change itself.

#### 4.2 Reload (or, if necessary, restart) Apache  

```bash
# Graceful reload – preserves existing connections
systemctl reload httpd

# If the reload does not clear the error, perform a full restart (drops active sessions)
# systemctl restart httpd
```

*Impact:* A **reload** is production‑safe; a **restart** should be scheduled during a maintenance window.

#### 4.3 Verify the fix  

```bash
# Confirm listening state
ss -tlnp | grep ':443'

# Test TLS handshake (ignore self‑signed warning)
curl -k https://<hostname> | head -n 5

# Ensure no new AVC denials
ausearch -m avc -ts recent | audit2allow -w
```

Successful `curl` output and an empty AVC list indicate the SELinux issue is resolved.

---

### 5. If the problem persists after SELinux relabeling

| Action | Command / step | Why it helps |
|--------|----------------|--------------|
| **5.1 Re‑check firewall** | `firewall-cmd --add-service=https --permanent && firewall-cmd --reload` | Guarantees port 443 is open in the *public* zone. |
| **5.2 Verify external ACLs** | (Contact network team / review cloud security groups) | Eliminates a non‑host‑level block. |
| **5.3 Confirm Apache VirtualHost configuration** | `grep -i '^<VirtualHost' -A5 /etc/httpd/conf.d/ssl.conf` | Ensures a `<VirtualHost *:443>` block exists and points to the correct cert/key paths. |
| **5.4 Look for other SSL errors** | `grep -i 'AH01909' /var/log/httpd/error_log` | May reveal mismatched key/cert, unsupported cipher, or encrypted key. |
| **5.5 Test with the default self‑signed cert** | Edit `ssl.conf` to point `SSLCertificateFile`/`SSLCertificateKeyFile` to `/etc/pki/tls/certs/localhost.crt` and `/etc/pki/tls/private/localhost.key`, then reload Apache. | If that works, the problem is specific to the new files (format, context, or permissions). |
| **5.6 Ensure the private key is not passphrase‑protected** | `openssl rsa -in /path/to/key.key -check -noout` – if prompted for a passphrase, re‑create the key without one or configure Apache to use an `SSLPassPhraseDialog` (not recommended for production). | An encrypted key will cause `AH01909` errors because Apache cannot supply the passphrase. |

---

### 6. Evidence required for closure  

1. **SELinux audit log** showing no `AVC` denials for `httpd_t` reading the cert/key (or a screenshot of `ausearch` output).  
2. **`ls -Z` output** confirming both files have `httpd_config_t` (or `httpd_sys_content_t`).  
3. **`ss -tlnp` output** proving Apache is listening on `*:443`.  
4. **Firewall listing** (`firewall-cmd --list-all --zone=public`) showing port 443/tcp or the `https` service enabled.  
5. **Successful TLS test** (`curl -k https://<hostname>` or `openssl s_client`) returning a valid handshake.  
6. **Apache error log** excerpt (last 20 lines) confirming no new SSL‑related errors after remediation.

---

### 7. Production‑impact warnings  

| Action | Potential impact | Mitigation |
|--------|------------------|------------|
| `restorecon` / `semanage` | None (labels only) | Run during normal operation. |
| `firewall-cmd --add-service=https` | May open port 443 to all sources in the zone | Verify zone is appropriate; consider limiting source IPs if required. |
| `systemctl reload httpd` | Graceful – no dropped connections | Safe for production. |
| `systemctl restart httpd` | Drops all active HTTP/HTTPS sessions | Schedule during a maintenance window or low‑traffic period. |
| Editing `ssl.conf` to point to a different cert | Temporary loss of expected certificate identity | Use a test hostname or inform stakeholders before change. |

---

### 8. Bottom line  

- The **most common** cause of the described HTTPS failure on RHEL 9 with SELinux enforcing is an **incorrect SELinux label** on the newly created certificate or private key.  
- **First‑line fix:** relabel the files with `httpd_config_t` (or `httpd_sys_content_t`) using `restorecon`/`semanage`, then **reload** Apache.  
- **If the issue remains**, systematically verify firewall rules, listening sockets, VirtualHost definitions, and certificate/key format as outlined in the checklist.  

Following the steps and providing the evidence items listed above will confirm that the server can successfully complete TLS handshakes with the self‑signed certificate.