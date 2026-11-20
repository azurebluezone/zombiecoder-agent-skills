<?php
declare(strict_types=1);

/**
 * Real PHP pack example.
 *
 * Run: php examples/packs/php_example.php
 *
 * The same file is both the CLI harness and the router for PHP's built-in
 * server. In CLI mode it starts `php -S` on a free loopback port, requests
 * /health and /missing, checks the JSON body, the nosniff header and the 404
 * status, then exercises password hashing and UTF-8 round-tripping. It prints
 * PHP_PACK_OK only when every check passes.
 */

const HEALTH_TITLE = 'php-pack-example';

if (PHP_SAPI === 'cli-server') {
    $uri = (string) ($_SERVER['REQUEST_URI'] ?? '/');
    $path = parse_url($uri, PHP_URL_PATH);
    $path = is_string($path) && $path !== '' ? $path : '/';

    header('X-Content-Type-Options: nosniff');
    if ($path === '/health') {
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode(
            [
                'ok' => true,
                'sapi' => PHP_SAPI,
                'php' => PHP_VERSION,
                'title' => HEALTH_TITLE,
                'bn' => 'স্বাস্থ্য পরীক্ষা',
            ],
            JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR
        );
        return;
    }

    http_response_code(404);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(
        ['ok' => false, 'error' => 'not_found'],
        JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR
    );
    return;
}

function fail(string $message): never
{
    fwrite(STDERR, "FAIL: {$message}\n");
    exit(1);
}

function free_port(): int
{
    $server = stream_socket_server('tcp://127.0.0.1:0', $errno, $errstr);
    if ($server === false) {
        fail("cannot reserve a port: {$errstr} ({$errno})");
    }
    $name = stream_socket_get_name($server, false);
    fclose($server);
    if (!is_string($name) || preg_match('/:(\d+)$/', $name, $match) !== 1) {
        fail('cannot parse the reserved port');
    }
    return (int) $match[1];
}

/**
 * @return array{status:int, headers:list<string>, body:string}
 */
function http_get(string $url): array
{
    $context = stream_context_create([
        'http' => [
            'method' => 'GET',
            'ignore_errors' => true,
            'timeout' => 5,
            'header' => "Connection: close\r\n",
        ],
    ]);
    $body = @file_get_contents($url, false, $context);
    $headers = $http_response_header ?? [];
    $status = 0;
    foreach ($headers as $header) {
        if (preg_match('#^HTTP/\S+\s+(\d{3})#', $header, $match) === 1) {
            $status = (int) $match[1];
        }
    }
    return [
        'status' => $status,
        'headers' => $headers,
        'body' => $body === false ? '' : $body,
    ];
}

$port = free_port();
$command = [PHP_BINARY, '-S', "127.0.0.1:{$port}", __FILE__];
$descriptors = [
    0 => ['pipe', 'r'],
    1 => ['pipe', 'w'],
    2 => ['pipe', 'w'],
];
$process = proc_open($command, $descriptors, $pipes, __DIR__);
if (!is_resource($process)) {
    fail('cannot start php -S');
}
fclose($pipes[0]);

$base = "http://127.0.0.1:{$port}";
$health = null;
$deadline = microtime(true) + 10.0;
while (microtime(true) < $deadline) {
    $state = proc_get_status($process);
    if (!$state['running']) {
        $stderr = stream_get_contents($pipes[2]);
        fail("php -S exited early: {$stderr}");
    }
    $response = http_get($base . '/health');
    if ($response['status'] === 200) {
        $health = $response;
        break;
    }
    usleep(100_000);
}

try {
    if ($health === null) {
        fail('php -S did not answer /health within 10s');
    }

    $headerBlock = implode("\n", $health['headers']);
    if (stripos($headerBlock, 'X-Content-Type-Options: nosniff') === false) {
        fail('health response is missing the nosniff header');
    }
    if (stripos($headerBlock, 'Content-Type: application/json') === false) {
        fail('health response is not JSON');
    }

    $payload = json_decode($health['body'], true, 512, JSON_THROW_ON_ERROR);
    if (!is_array($payload)) {
        fail('health body is not a JSON object');
    }
    if (($payload['ok'] ?? null) !== true) {
        fail('health body did not report ok=true');
    }
    if (($payload['sapi'] ?? '') !== 'cli-server') {
        fail('health body reported the wrong SAPI');
    }
    if (($payload['php'] ?? '') !== PHP_VERSION) {
        fail('health body reported the wrong PHP version');
    }
    if (($payload['bn'] ?? '') !== 'স্বাস্থ্য পরীক্ষা') {
        fail('Bengali text did not round-trip through JSON');
    }

    $missing = http_get($base . '/missing');
    if ($missing['status'] !== 404) {
        fail("unknown path returned {$missing['status']}, expected 404");
    }
    $missingPayload = json_decode($missing['body'], true, 512, JSON_THROW_ON_ERROR);
    if (!is_array($missingPayload) || ($missingPayload['error'] ?? '') !== 'not_found') {
        fail('unknown path did not return the expected JSON error');
    }

    $hash = password_hash('correct horse battery staple', PASSWORD_DEFAULT);
    if (!is_string($hash) || !password_verify('correct horse battery staple', $hash)) {
        fail('password hash round-trip failed');
    }
    if (password_verify('wrong password', $hash)) {
        fail('password_verify accepted the wrong password');
    }

    $token = bin2hex(random_bytes(16));
    if (strlen($token) !== 32) {
        fail('random token has the wrong length');
    }

    $bengali = 'বাংলা টেক্সট পরীক্ষা';
    $decoded = json_decode(json_encode($bengali, JSON_THROW_ON_ERROR), true, 512, JSON_THROW_ON_ERROR);
    if ($decoded !== $bengali || mb_strlen($bengali, 'UTF-8') < 5) {
        fail('Bengali UTF-8 round-trip failed');
    }

    echo 'php ' . PHP_VERSION . " built-in server port={$port} health=200 nosniff=ok missing=404\n";
    echo 'crypto=password_hash+random_bytes utf8=' . mb_strlen($bengali, 'UTF-8') . " chars\n";
    echo "PHP_PACK_OK\n";
} finally {
    proc_terminate($process);
    $deadline = microtime(true) + 5.0;
    while (microtime(true) < $deadline) {
        $state = proc_get_status($process);
        if (!$state['running']) {
            break;
        }
        usleep(50_000);
    }
    $state = proc_get_status($process);
    if ($state['running']) {
        proc_terminate($process, 9);
    }
    fclose($pipes[1]);
    fclose($pipes[2]);
    proc_close($process);
}
