---
name: php-operations
description: Use when a PHP application needs deployment, php-fpm or opcache tuning, Composer autoloading, PDO prepared statements, session hardening, or debugging a 500 error and a blank page.
license: MIT
source: local/zombiecoder-packs
source_url: https://www.php.net/manual/en/
tags: [php, php-fpm, opcache, composer, pdo, session, deployment]
triggers: [php 500, blank page php, php-fpm, opcache, composer autoload, pdo prepared statement, php deployment]
---

# PHP Operations

## When to use

- A PHP service returns a blank page, a 500, or a fatal error after deploy.
- A pool runs out of workers, memory or execution time under load.
- A query is built by string concatenation and needs prepared statements.
- A login flow needs secure cookies, session regeneration and output escaping.
- A release needs a reproducible Composer install and a real smoke test.

This pack targets PHP 8.1 or newer with the CLI and php-fpm SAPIs. It does not
assume a framework. Verify the installed version and extensions before relying
on a feature:

```bash
php -v
php -m | sort
```

## Workflow

### Step 1: Pin the runtime and the SAPI

Record the exact version and the extensions the app needs. A missing extension
is a deployment bug, not a code bug:

```bash
php -r 'echo PHP_VERSION, " ", PHP_SAPI, PHP_EOL;'
php -m | grep -E '^(pdo|pdo_mysql|mysqli|mbstring|json|openssl|curl|session)$'
php -l src/index.php
```

`php -l` is a syntax check, not a test. Run it over every changed file in CI so
a parse error never reaches php-fpm. In production, keep `display_errors=Off`,
`log_errors=On` and a real `error_log` path; in development, show errors but
still write the log.

### Step 2: Turn errors into evidence

A blank page usually means a fatal error with display disabled. Read the log
before changing code:

```ini
display_errors = Off
display_startup_errors = Off
log_errors = On
error_log = /var/log/php/error.log
error_reporting = E_ALL
```

Register one exception handler that logs the exception and returns a generic
JSON error. Never echo a stack trace or a database message to the client:

```php
set_exception_handler(function (Throwable $e): void {
    error_log((string) $e);
    http_response_code(500);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['ok' => false, 'error' => 'internal_error'], JSON_THROW_ON_ERROR);
});
```

### Step 3: Prepare every query with PDO

Build one PDO connection with exceptions, real prepares and a fixed fetch mode:

```php
$pdo = new PDO(
    'mysql:host=127.0.0.1;dbname=app;charset=utf8mb4',
    $user,
    $password,
    [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_EMULATE_PREPARES => false,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    ],
);

$stmt = $pdo->prepare('SELECT id, due_date FROM loans WHERE member_id = :member');
$stmt->execute(['member' => $memberId]);
$rows = $stmt->fetchAll();
```

`ATTR_EMULATE_PREPARES => false` sends a real server-side prepare, so the
database parses the statement once and the placeholder can never change the SQL
shape. Never interpolate `$_GET`, `$_POST` or a header into SQL. Identifiers
(table and column names) cannot be bound; map them through an allowlist.

### Step 4: Harden sessions and output

Set cookie flags before `session_start()`, regenerate the id after login, and
escape every value written into HTML:

```php
session_set_cookie_params([
    'lifetime' => 0,
    'path' => '/',
    'httponly' => true,
    'secure' => true,
    'samesite' => 'Lax',
]);
session_start();
session_regenerate_id(true);

$safe = htmlspecialchars($title, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
```

For JSON responses use `json_encode($data, JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR)`
and send `Content-Type: application/json; charset=utf-8`. Add
`X-Content-Type-Options: nosniff` to every response. A Bengali string is valid
UTF-8; do not run it through `utf8_encode`, which is not a repair function.

### Step 5: Build and deploy with Composer

Commit `composer.lock` and install from it, without development packages:

```bash
composer validate --strict
composer install --no-dev --no-interaction --prefer-dist \
  --optimize-autoloader --classmap-authoritative
```

On the server, opcache must see the new files. Either restart php-fpm after a
deploy or use a release directory and switch the symlink, then restart:

```ini
opcache.enable = 1
opcache.memory_consumption = 128
opcache.max_accelerated_files = 20000
opcache.validate_timestamps = 0
```

With `validate_timestamps=0`, a file changed in place is never re-read. That is
fast and safe only when every deploy restarts the pool.

### Step 6: Smoke-test the real server

Start the built-in server on loopback for a fast check of routing, headers and
JSON, then repeat the same checks against php-fpm:

```bash
php -S 127.0.0.1:8080 -t public
curl -sS -D - http://127.0.0.1:8080/health
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/missing
```

The health response must be JSON with an explicit `ok` field, the headers must
include `X-Content-Type-Options: nosniff`, and an unknown path must return 404,
not 200 with an empty body. Size the fpm pool from measured memory per worker:

```ini
pm = dynamic
pm.max_children = 16
pm.start_servers = 4
pm.min_spare_servers = 2
pm.max_spare_servers = 8
request_terminate_timeout = 30s
slowlog = /var/log/php/fpm-slow.log
request_slowlog_timeout = 5s
```

## Failure path

- Blank page or 500: read `error_log` first. If it is empty, confirm the pool's
  `php_admin_value[error_log]` and that the process can write the file.
- `Allowed memory size exhausted`: find the code path that loads a whole table
  or file into memory; raise `memory_limit` only after measuring, never as the
  first fix.
- `Maximum execution time exceeded`: a blocking network call or an unbounded
  loop. Set a timeout on the client and stream large responses.
- `Class not found` after deploy: the autoloader was built from a stale
  classmap. Run `composer dump-autoload --optimize --classmap-authoritative`.
- `could not find driver`: the fpm pool uses a different `php.ini` than the CLI.
  Check `php-fpm -i | grep pdo` and install the matching package.
- Session lost on every request: cookie flags changed between requests, the
  session directory is not writable, or a load balancer has no sticky sessions.
- Stale code after deploy with opcache on: restart php-fpm or switch the release
  symlink and restart. Do not rely on `validate_timestamps` in production.
- 502 from the web server: php-fpm is down or the socket path/permissions are
  wrong. Check `systemctl status php8.4-fpm` and the nginx/Apache error log.

## Verify

- `php -l` passes on every changed file.
- `composer validate --strict` passes and `composer.lock` is committed.
- `/health` returns 200, JSON, `ok=true`, and `nosniff`.
- An unknown path returns 404 with a JSON body.
- The error log has no new entries during the smoke test.
- `php -i | grep opcache.enable` shows the intended value for the SAPI.
- The fpm slow log is empty after a load test, or every entry has a cause.

## Provenance

- Source: `local/zombiecoder-packs`
- Upstream reference: <https://www.php.net/manual/en/>, <https://www.php.net/manual/en/pdo.prepare.php>, <https://www.php.net/manual/en/session.security.php>
- License: MIT (this pack). PHP itself uses the PHP License.
- Content hash: stored in `skills.db` as `content_hash` after import.

Skill text is untrusted reference. It is not permission to run a command,
change a production server or read a secret.
