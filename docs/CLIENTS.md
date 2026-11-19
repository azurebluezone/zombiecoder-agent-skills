# Client compatibility — `https://gpu.zombiecoder.my.id`

Short answer: **yes**, the endpoint is a standard OpenAI-compatible API and can
be added to OpenCode or a VS Code AI extension as a custom OpenAI provider.
It is a model endpoint, not a skill server: skill routing happens on the client
side (or in a proxy) with this library before the request is sent.

## Verified surface (2026-11-20)

All requests used `Authorization: Bearer <gateway key>` unless noted.

| Check | Result |
| --- | --- |
| `GET /api/health` | `200`, TLS verify `0` (valid certificate) |
| `GET /v1/models` without a key | `401 authentication_error` |
| `GET /v1/models` with the key | `200`, two models |
| `POST /v1/chat/completions` | `200`, content `ready` |
| `POST /v1/chat/completions` `stream:true` | SSE chunks with `delta.content` |
| `POST /v1/chat/completions` with `tools` | `200`, `finish_reason: tool_calls`, arguments `{"city":"Dhaka"}` |
| `POST /v1/responses` | `200`, `status: completed`, `output_text` present |
| `POST /v1/messages` (Anthropic shape) | `200`, `type: message`, text block |
| `GET /v1/client-config` | `200`, base URL + endpoint map + examples |
| `OPTIONS /v1/chat/completions` | `204`, `access-control-allow-origin: *` |

Models observed:

```
Llama-3.2-3B-Instruct-Q4_K_M
Muse-12B.i1-IQ2_XXS
```

The exact list changes with what is loaded on the GPU host. Query
`GET /v1/models` instead of hard-coding it.

## Authentication

- OpenAI-style clients: `Authorization: Bearer <key>`
- Anthropic-style clients: `x-api-key: <key>` plus
  `anthropic-version: 2023-06-01`; the gateway also accepted
  `Authorization: Bearer` for `/v1/messages` in testing
- The key is also at `GET /v1/client-config` once authenticated, and in the
  gateway runtime file `.zombiecoder/api_key.txt`

Never commit the key. Put it in an environment variable.

## OpenCode

The current provider docs describe a custom provider with the
`@opencode/ai/providers/openai-compatible` package. Add this to
`opencode.jsonc` (global or project):

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "providers": {
    "zombiecoder": {
      "name": "ZombieCoder GPU",
      "env": ["ZOMBIECODER_API_KEY"],
      "package": "@opencode/ai/providers/openai-compatible",
      "settings": {
        "baseURL": "https://gpu.zombiecoder.my.id/v1"
      },
      "models": {
        "Llama-3.2-3B-Instruct-Q4_K_M": {
          "name": "Llama 3.2 3B (gateway)"
        },
        "Muse-12B.i1-IQ2_XXS": {
          "name": "Muse 12B (gateway)"
        }
      }
    }
  }
}
```

```bash
export ZOMBIECODER_API_KEY="$(cat .zombiecoder/api_key.txt)"
opencode
```

Then select `zombiecoder/Llama-3.2-3B-Instruct-Q4_K_M`. The provider ID becomes
the prefix in model references.

Caveat: a 3B local model is fine for smoke tests and simple edits, but it is
weak at long tool-calling loops. Use `Muse-12B.i1-IQ2_XXS` or a larger loaded
model when OpenCode's agent loop misbehaves.

## VS Code

VS Code itself does not let GitHub Copilot point at a custom base URL. Use an
extension that supports an OpenAI-compatible provider. The common choice is
**Continue** (`config.yaml`):

```yaml
models:
  - name: ZombieCoder Llama
    provider: openai
    model: Llama-3.2-3B-Instruct-Q4_K_M
    apiBase: https://gpu.zombiecoder.my.id/v1
    apiKey: $ZOMBIECODER_API_KEY
    roles:
      - chat
      - edit
      - apply
```

Set the key in the environment Continue inherits, or replace `$ZOMBIECODER_API_KEY`
with the literal key in your user-level config (not in a shared repo).

Continue's schema changes between major versions; if the editor rejects a
field, check the version's model-setup page. The values that matter are:
`provider: openai`, `apiBase` ending in `/v1`, the exact model ID from
`/v1/models`, and the bearer key.

## curl

```bash
export ZOMBIECODER_API_KEY="$(cat .zombiecoder/api_key.txt)"
export BASE="https://gpu.zombiecoder.my.id/v1"

curl "$BASE/models" -H "Authorization: Bearer $ZOMBIECODER_API_KEY"

curl "$BASE/chat/completions" \
  -H "Authorization: Bearer $ZOMBIECODER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"Llama-3.2-3B-Instruct-Q4_K_M","messages":[{"role":"user","content":"ready?"}],"max_tokens":16}'

# streaming
curl -N "$BASE/chat/completions" \
  -H "Authorization: Bearer $ZOMBIECODER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"Llama-3.2-3B-Instruct-Q4_K_M","messages":[{"role":"user","content":"Count 1 to 3"}],"stream":true}'
```

## Adding the skill library

The gateway does not inject skills into external client requests. To get the
library into an OpenCode/Continue session, either:

1. run a small proxy that calls `SkillStore.inject()` before forwarding to
   `/v1/chat/completions`, or
2. paste the selected `SKILL.md` body into the project's rules/instructions
   file for the session, or
3. use the gateway's own admin chat, which already injects the top 2 skills
   when `skill_anchor` is on.

Option 1 keeps routing dynamic; options 2 and 3 are simpler and more
predictable.

## Compatibility limits

- Only the listed OpenAI and Anthropic shapes were tested. Embeddings/rerank
  are exposed by the gateway but depend on a loaded model that supports them.
- The endpoint requires a key; a client that cannot send a custom header cannot
  connect.
- CORS is open (`*`), so browser-based clients work, but that also means the key
  is the only access control. Keep it private.
- Tool calling worked with the 3B model for a single simple function; multi-turn
  tool loops on small models are unreliable.
- `/v1/responses` and `/v1/messages` are gateway translations; use the OpenAI
  chat shape if a client offers both.
