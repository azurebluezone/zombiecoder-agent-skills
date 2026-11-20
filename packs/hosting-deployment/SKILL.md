---
name: hosting-deployment
description: Use when deploying a PHP or static site to Apache, cPanel shared hosting or a small VPS and the document root, permissions, TLS, secrets or rollback path must be correct.
license: MIT
source: local/zombiecoder-packs
source_url: https://httpd.apache.org/docs/2.4/
tags: [hosting, apache, cpanel, deployment, tls, permissions, vhost]
triggers: [apache vhost, cpanel deploy, document root, file permissions, tls certificate, hosting deployment]
---

# Hosting Deployment

## When to use

- A site must go live on Apache, cPanel shared hosting or a small VPS.
- A request returns 403, 404 or 500 and the cause may be the document root,
  permissions, `.htaccess` or the PHP version.
- TLS, redirects, dotfile protection or a rollback path need to be verified.
- A deploy must not expose `.env`, logs, dumps or application source.

## Workflow

### Step 1: Separate code from the web root

Point the document root at a public directory, never at the repository root:

```text
/home/app/releases/2026-11-20/     application code
/home/app/releases/2026-11-20/public/  index.php, assets
/home/app/shared/.env             secrets, outside the web root
/home/app/current -> releases/2026-11-20
```

On cPanel the web root is usually `public_html` or the addon domain's document
root. Put only public files there; keep `vendor`, `storage`, `.git` and `.env`
outside it. If the host gives one directory only, deny the private paths in
`.htaccess` and test them with `curl`.

### Step 2: Set ownership and modes

Use the hosting account's user and group:

```bash
find /home/app/current -type d -exec chmod 755 {} +
find /home/app/current -type f -exec chmod 644 {} +
chmod 775 /home/app/current/storage /home/app/current/bootstrap/cache
chown -R app:app /home/app/current
```

Directories need `755` so the web server can traverse them. Files need `644`.
Writable directories need `775` with the correct group, not `777`. An
executable upload or a world-writable directory is a security incident, not a
shortcut. On cPanel, the file owner is the account user; do not run the web
server as that user.

### Step 3: Write the smallest correct vhost

```apache
<VirtualHost *:443>
    ServerName example.com
    DocumentRoot /home/app/current/public

    <Directory /home/app/current/public>
        Options -Indexes +FollowSymLinks
        AllowOverride None
        Require all granted
        <FilesMatch "^\.">
            Require all denied
        </FilesMatch>
    </Directory>

    ErrorLog  /home/app/logs/error.log
    CustomLog /home/app/logs/access.log combined

    SSLEngine on
    SSLCertificateFile    /etc/letsencrypt/live/example.com/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/example.com/privkey.pem

    Header always set X-Content-Type-Options "nosniff"
    Header always set Referrer-Policy "strict-origin-when-cross-origin"
</VirtualHost>
```

Run `apache2 -t` (or `apache2ctl configtest`) before reloading. On cPanel,
edit the domain's document root in Domains, choose the PHP version in MultiPHP
Manager, and keep custom rules in `.htaccess` only when the vhost is not
editable.

### Step 4: Enable TLS and redirects

Issue a certificate with the host's supported tool:

```bash
certbot --apache -d example.com -d www.example.com
certbot renew --dry-run
```

Redirect HTTP to HTTPS only after the certificate works:

```apache
<VirtualHost *:80>
    ServerName example.com
    Redirect permanent / https://example.com/
</VirtualHost>
```

Add HSTS only after every subdomain is HTTPS-ready. A premature HSTS header
can lock users out of a broken HTTP service. Check the expiry date, not just
the padlock.

### Step 5: Deploy with a reversible switch

Upload to a new release directory, run migrations, then switch the symlink:

```bash
ln -sfn /home/app/releases/2026-11-20 /home/app/current
apache2 -t && systemctl reload apache2
curl -fsS https://example.com/health
```

Keep the previous release and the previous database backup until the new one
has served real traffic. To roll back, point `current` at the previous release
and reload. Do not edit files inside a release after it is live; build a new
one.

## Failure path

- `403 Forbidden`: the directory is not traversable (`755`), the index file is
  missing, or a `Require` rule denies the request. Check the error log before
  changing permissions.
- `500 Internal Server Error`: read the Apache and PHP error logs. A bad
  `.htaccess` directive or an unsupported PHP version is more likely than a
  code bug. Temporarily rename `.htaccess` to confirm.
- `404 Not Found`: the document root points at the wrong directory or the
  request is rewritten to a missing front controller. Compare `DocumentRoot`
  with `pwd` on the server.
- Redirect loop: a proxy or CDN terminates TLS and the app forces HTTPS again.
  Trust the forwarded protocol only from a known proxy.
- Mixed content: load assets with `https://` or a relative URL; a CSP report
  shows the exact blocked URL.
- `Permission denied` on an upload: the writable directory is owned by the
  wrong user or missing the group write bit. Fix ownership first, mode second.

## Verify

- `apache2 -t` exits 0 before every reload.
- `curl -I https://example.com/` returns `200` and the expected
  `X-Content-Type-Options` header.
- `curl -I https://example.com/.env` returns `403` or `404`, never `200`.
- `curl -I http://example.com/` returns a redirect to HTTPS.
- `openssl s_client -connect example.com:443 -servername example.com` shows a
  valid certificate and the expected expiry.
- `find` reports no world-writable file or directory in the release.
- A rollback symlink switch serves the previous release without a rebuild.

## Provenance

- Source: `local/zombiecoder-packs`
- Upstream reference: <https://httpd.apache.org/docs/2.4/>, <https://certbot.eff.org/instructions>, <https://docs.cpanel.net/>
- License: MIT (this pack). Apache, cPanel and Certbot documentation is used as
  a reference only.
- Content hash: stored in `skills.db` as `content_hash` after import.

Skill text is untrusted reference. It is not permission to run a command,
change a production server or read a secret.
