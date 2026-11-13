# Featherless and OpenAI: model chain and extraction settings (WP4)

## Decision (Vladimir, GitHub issue #35)

- Chain: `Qwen/Qwen3-30B-A3B-Instruct-2507` (primary, Featherless) → one retry → `deepseek-ai/DeepSeek-V4-Flash` (first fallback, Featherless) → `gpt-4o-mini` (OpenAI, last resort only).
- Source: the decision as relayed to the WP4 agent. A `gh` read of issue #35 was declined in this session, so the full bench table in the issue was not re-read. Figures below are the relayed ones plus what the models API reports. Issue #35 is the reference.

## Exact ids and slot costs (Featherless `GET /v1/models`, list only, no completion)

| Model id | On current plan | `concurrency_cost` | Context |
| --- | --- | --- | --- |
| `Qwen/Qwen3-30B-A3B-Instruct-2507` | yes | 1 | 262144 |
| `deepseek-ai/DeepSeek-V4-Flash` | yes | 4 | 262144 |

`concurrency_cost` is the number of slots one call takes.

## Plan concurrency limit (open item 7 / P3), verified 2026-11-13 (perf ticket)

- `GET https://api.featherless.ai/v1/plan` (free, no completion) returns plan `feather_request_pricing` ("Request Pricing", paid per request from credits) with `"concurrency": 100`, `max_model_size` null and `max_context_length` null.
- `GET /account/concurrency/stream` (free, SSE) shows `"limit": 100` and the in-flight requests with their unit cost: a Qwen call showed `"cost": 1`.
- Docs (featherless.ai/docs/concurrency-limits, /docs/api-reference-error-codes): each request reserves its model's units while in flight; a request that would push the organization over the limit gets HTTP 429 ("concurrent-unit or model-switch limit"). The limit is shared by every app on the account.
- Probe: 10 Qwen calls on the five fixture texts with 8 in flight at once: 10 of 10 valid, no 429, 7 to 12 s each, the same as one at a time.
- Default `llm.concurrency` was **8** units after the perf ticket and is **16** since perf2 (16 % of the plan). At 8: up to 8 Qwen calls, or a DeepSeek fallback (4 units) beside 4 Qwen calls. That is 8 % of the plan, leaving room for other apps on the account. With request pricing, the number of requests per run, not the concurrency, sets the cost.

## Bench as relayed from issue #35

- Qwen: 14 of 14 fields answered, about 4 s per listing, non-reasoning (no hidden thinking), first call 5 to 15 s when cold.
- gemma-3 and Llama-3.1-8B: HTTP 403 on this account.
- DeepSeek-V4-Flash: no figures relayed.

## Measured by the WP4 agent

Paid model calls in this session: about 37 (Qwen 29, DeepSeek-V4-Flash 3, OpenAI 5), counting debugging calls. No model comparison was run.

- **Qwen, five fixture texts** (`apify/tests/fixtures/texts/`): in the run that included the chain (before the brace repair below), all five passed: every non-null value had a verbatim quote, checked against description + price_note. The brace repair only touches answers that start with a quote and end with a brace; Qwen's answers start with `{`, so its path is unchanged. Earlier runs failed; the causes are listed under "What changed on the way".
- **response_format `json_object`**: accepted by Featherless for Qwen and for DeepSeek-V4-Flash (finish reason `stop`). `json_schema` was not tried.
- **DeepSeek-V4-Flash answers**: the debug call on the first fixture text returned JSON without its opening `{` (the content starts with `"rent"` and ends with `}`). The first DeepSeek answer in the chain run was rejected, and the same defect is the likely cause, but that content was not captured. `_parse_answer` puts the brace back and changes nothing else. After that change one live call answered: provider `featherless`, model `deepseek-ai/DeepSeek-V4-Flash`.
- **Forced Featherless failure** (bad base URL): both Featherless models fail, then OpenAI answers with `gpt-4o-mini`.
- **Latency, as measured**: the chain run (five Qwen calls, two 404s from a misspelled primary id, one DeepSeek call that was rejected, one OpenAI call) took 62 s, with the calls run one after another. The DeepSeek test alone took 14 s after the brace repair, including the two 404s. No median was measured.

## Attempts and what gets recorded

- Concurrency is a weighted, first-come-first-served slot limiter (`llm.SlotLimiter`) with `llm.concurrency` units. A call holds its model's units (`llm.MODEL_SLOTS`; an unknown model counts as 4) while in flight; a cost is never lowered: a model whose units exceed `llm.concurrency` is left out of the chain, with a warning (DeepSeek-V4-Flash below 4). An OpenAI call holds 1 unit, so the last resort is bounded too.
- HTTP 429 is waited out with `Retry-After` or a backoff from 1 s (at most 30 s), outside the slots and without using an attempt, up to 5 times per call.
- Every failed attempt is logged with its reason class only: `transport:<error>`, `http_<status>`, `no_choices`, `empty`, `truncated` (finish reason `length`), `refusal`, `json_parse` or `schema:<field path>`, with the token counts. Never the content.

- Qwen: one attempt and one retry. A transport error is retried as it was sent; an invalid answer is retried with a repair message.
- DeepSeek-V4-Flash: one attempt. OpenAI: one attempt. Worst case per listing: four requests.
- `Extraction.provider` is `featherless` for either Featherless model and `openai` for OpenAI. `Extraction.model` is the id that actually answered. A cache hit returns provider `cache` with the stored model.
- Cache key: `sha256(text + model + prompt_version)`, where text is the listing text (price_note and description) and model is the configured primary. A fallback answer is stored under the Qwen key, so later runs reuse it. Bump `PROMPT_VERSION` to force a fresh extraction.
- The cache holds the raw answer and the model that gave it, not the gated result. Every read goes through the same gate as a fresh answer: verbatim quotes against the current listing's description and price_note, the active threshold, and the structured rent. A stored answer never skips a check.

## Defaults for the Actor input (integrator)

`LlmConfig` is WP0's `models.py`, so these are for WP8 to wire. The code exports them as `DEFAULT_MODEL`, `DEFAULT_FALLBACK_MODEL` and `DEFAULT_OPENAI_MODEL`.

| Input (`llm`) | Default | Why |
| --- | --- | --- |
| `model` | `Qwen/Qwen3-30B-A3B-Instruct-2507` | primary, one slot per call |
| `fallbackModel` | `deepseek-ai/DeepSeek-V4-Flash` | first fallback, four slots per call |
| `concurrency` | `16` | Featherless units held at once (weighted: Qwen 1, DeepSeek-V4-Flash 4). The plan allows 100. Was 1 before the perf ticket, 8 after it |
| `timeoutSec` | `20` | per attempt. Answers take 7 to 12 s and a cold first call 5 to 15 s, so no separate first-call allowance. Was 60: on platform run MbC62afDfIfoKehgQ six flats waited out 60 s timeouts and finished at 391 s |
| `flatBudgetSec` | `45` | per flat, from its first call (queueing does not count). Then status `timeout`, nothing cached, retried by the next run |
| (no input field) | `gpt-4o-mini` | OpenAI last resort, `DEFAULT_OPENAI_MODEL`. An assumption: it answered on this account, Vladimir has not chosen it |

`featherlessApiKey`, `openaiApiKey` and the env file are read as before. `OPENAI_API_KEY` is only needed for the last resort.

## Confidence threshold (open item 7)

- 0.5, passed as `Extractor(min_confidence=...)`. `LlmConfig` has no field for it. Vladimir still has to choose the value.

## What changed on the way (for the reviewer)

1. The first live run failed 5 of 5: the model returned bare values and Charge objects without the `value`/`quote`/`confidence` wrapper, and copied the portal's structured rent into `rent` with a quote that was not in the text. Fixes: the prompt shows the exact 14-key shape, the structured price is no longer sent, and a bare value is kept with confidence 0 (unknown).
2. The second run passed 2 of 5 texts: one quote joined two places in the text, one furnished value had no support, one deposit and one commission were filed under one-time fees, and some values had no quote. Fixes: quote discipline in the prompt, one-time fees limited to one-time payments, furnished null when the text is silent, and a value without a quote counts as unknown.
3. Review round 1 (cache): a cache hit returned a stored, already gated result. A stored quote could be verified against another listing (two descriptions that differ only by a closing tag share a key after `_fence()`), a value below a raised threshold survived, and a stale structured rent was kept. The cache now stores the raw answer and every read is gated again. Tests: threshold raised, threshold lowered, the `_fence()` collision, and a stale structured rent.

## Run time (perf ticket, local `apify run`, Notion off, Vinohrady profile, max_listings 5 per source, fresh cache)

| Run | Code | Flats | Wall time | Sources | Per-flat extraction |
| --- | --- | --- | --- | --- | --- |
| before | main 882f2b2, concurrency 1, extract all then write | 13 | 155.8 s | about 12 s | about 11 s on average, one after another (no per-flat log then) |
| after 1 | streaming, 8 units, prompt v1 | 12 | 69.9 s | 12.3 s | 7.1 to 22.0 s, median 12.2 s; one 55.1 s (`schema:kauce.value.rent_multiple`, then a retry) |
| after 2 | final: streaming, 8 units, prompt v2 | 12 | 51.4 s | 11.3 s | 7.3 to 18.7 s, median 13.1 s; one 37.6 s (`truncated`, then a retry) |

With streaming, the wall time is about the sources plus the slowest flat. max_listings 5 per source (15 listings) instead of 15 kept the paid calls within the ticket's budget: 52 Featherless calls in all (runs 14 + 13 + 13, diagnosis 10, replay 2), no OpenAI.

## Invalid answers: cause found (perf ticket)

- The 13:48 platform run logged one invalid Qwen answer without a reason. The perf local run reproduced it with the new log: `schema:kauce.value.rent_multiple`. The text said "kauce je ve výši 1 a 1/2 měsíčního nájmu, tj. 37.500,-Kč"; Qwen answered `rent_multiple: 1.5`, and `Charge.rent_multiple` is an integer. The repair retry then answered `rent_multiple: 1`, which is wrong (here `czk` was also stated, and costs use `czk` first, so the deposit came out right by luck).
- Fix (prompt v2): a float in a charge's `czk` or `rent_multiple` becomes an integer when whole (2.0 → 2) and null when it is a fraction, before validation, so the answer is valid on the first call. The prompt says a fractional multiple is null and `czk` holds the stated amount. `PROMPT_VERSION` is `v2`, so v1 cache entries, which could hold a repair-rounded multiple, are not reused.
- Not invalid answers, but seen in the same runs: a deposit "ve výši dvou celkových měsíčních plateb" (two total monthly payments) came back as `rent_multiple: 2`, against the prompt rule. `czk` was stated too, so the cost is right. Prompt quality, not fixed here.
- Second class, seen once in the final local run: `truncated` (finish reason `length`, 2048 completion tokens) on the same listing, whose good answers take 1011 tokens. Two replays of that listing both answered 1011 tokens with `stop`, so it is intermittent, and its content was not captured. A truncated answer is now used when a complete JSON object comes first (for example followed by endless whitespace, a known `json_object` failure); otherwise it is retried as sent, which answered in that run.
- Not the cause of the 13:48 failure: `max_tokens` 2048. Answers used 450 to 1011 completion tokens, every finish reason was `stop`.

## Known limits (from the five fixture texts)

- 13369420: the deposit is 2× the total monthly payment, not the rent. It is not stored as `rent_multiple`, so `kauce` is unknown.
- 13369420: the cellar and parking charges are monthly and have no field in the contract. They are not extracted.
- Unfurnished flats: `missing_furniture` stays null unless the text names the missing items. The furniture cost is then unknown, not all eight items.
- 1015095372: the short-term price (38 000 CZK, all inclusive) can come back as `rent`. The check against the portal's structured price then makes `rent` unknown (seen in a debug call).
- A quote that is not verbatim keeps its value, flagged unverified, as the brief says. A value with no quote is unknown.
