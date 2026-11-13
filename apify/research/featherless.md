# Featherless and OpenAI: model chain and extraction settings (WP4)

## Decision (Vladimir, GitHub issue #35)

- Chain: `Qwen/Qwen3-30B-A3B-Instruct-2507` (primary, Featherless) → one retry → `deepseek-ai/DeepSeek-V4-Flash` (first fallback, Featherless) → `gpt-4o-mini` (OpenAI, last resort only).
- Source: the decision as relayed to the WP4 agent. A `gh` read of issue #35 was declined in this session, so the full bench table in the issue was not re-read. Figures below are the relayed ones plus what the models API reports. Issue #35 is the reference.

## Exact ids and slot costs (Featherless `GET /v1/models`, list only, no completion)

| Model id | On current plan | `concurrency_cost` | Context |
| --- | --- | --- | --- |
| `Qwen/Qwen3-30B-A3B-Instruct-2507` | yes | 1 | 262144 |
| `deepseek-ai/DeepSeek-V4-Flash` | yes | 4 | 262144 |

`concurrency_cost` is the number of slots one call takes. The API does not report the account's total slot limit; that is plan concurrency (open item 7), still open.

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
| `concurrency` | `1` | WP0's `LlmConfig` default is 2. At 2, a Qwen call and a DeepSeek call could hold 5 slots at once; at 1, at most 4 |
| `timeoutSec` | `60` | covers the 5 to 15 s cold start |
| (no input field) | `gpt-4o-mini` | OpenAI last resort, `DEFAULT_OPENAI_MODEL`. An assumption: it answered on this account, Vladimir has not chosen it |

`featherlessApiKey`, `openaiApiKey` and the env file are read as before. `OPENAI_API_KEY` is only needed for the last resort.

## Confidence threshold (open item 7)

- 0.5, passed as `Extractor(min_confidence=...)`. `LlmConfig` has no field for it. Vladimir still has to choose the value.

## What changed on the way (for the reviewer)

1. The first live run failed 5 of 5: the model returned bare values and Charge objects without the `value`/`quote`/`confidence` wrapper, and copied the portal's structured rent into `rent` with a quote that was not in the text. Fixes: the prompt shows the exact 14-key shape, the structured price is no longer sent, and a bare value is kept with confidence 0 (unknown).
2. The second run passed 2 of 5 texts: one quote joined two places in the text, one furnished value had no support, one deposit and one commission were filed under one-time fees, and some values had no quote. Fixes: quote discipline in the prompt, one-time fees limited to one-time payments, furnished null when the text is silent, and a value without a quote counts as unknown.
3. Review round 1 (cache): a cache hit returned a stored, already gated result. A stored quote could be verified against another listing (two descriptions that differ only by a closing tag share a key after `_fence()`), a value below a raised threshold survived, and a stale structured rent was kept. The cache now stores the raw answer and every read is gated again. Tests: threshold raised, threshold lowered, the `_fence()` collision, and a stale structured rent.

## Known limits (from the five fixture texts)

- 13369420: the deposit is 2× the total monthly payment, not the rent. It is not stored as `rent_multiple`, so `kauce` is unknown.
- 13369420: the cellar and parking charges are monthly and have no field in the contract. They are not extracted.
- Unfurnished flats: `missing_furniture` stays null unless the text names the missing items. The furniture cost is then unknown, not all eight items.
- 1015095372: the short-term price (38 000 CZK, all inclusive) can come back as `rent`. The check against the portal's structured price then makes `rent` unknown (seen in a debug call).
- A quote that is not verbatim keeps its value, flagged unverified, as the brief says. A value with no quote is unknown.
