# Pi per-model settings applied

Only provider-listed limits were used. Unverified limits retain Pi's existing defaults. The original model entries omitted both fields; Pi 1.5.2 documents defaults of contextWindow 128000 and maxTokens 16384 in its installed docs/models-configuration.md.

| Model | Old context → new context | Old max output → new max output | Source / verification |
|---|---:|---:|---|
| xingchi/gpt-6-astra | 128000 → 128000 | 16384 → 16384 | https://api.xingchiapi.com/v1/models lists ID/display name but no limits. Both limits **unverified**, defaults retained. |
| xingchi/gpt-6.1-sol | 128000 → 128000 | 16384 → 16384 | https://api.xingchiapi.com/v1/models lists ID/display name but no limits. Both limits **unverified**, defaults retained. |
| tokenlab/DeepSeek-V4.1-Flash | 128000 → 1048576 | 16384 → 16384 | https://api.tokenlab.amd.com/v1/models explicitly lists `context_length: 1048576`. Maximum output **unverified**, default retained; listing `max_tokens` as a supported parameter does not document its maximum. |
| moss/nex-n2.6 | 128000 → 128000 | 16384 → 16384 | https://api.mosi.cn/v1/models lists ID/owner but no limits. Both limits **unverified**, defaults retained. |
| howtofix/deepSeek-v4.1-flash-1017-sg | 128000 → 128000 | 16384 → 16384 | https://api.howtofix.id/v1/models lists ID/endpoint type but no limits. Both limits **unverified**, defaults retained. |

All four authenticated model-list requests succeeded. Raw provider responses and matching-entry summary are saved in `/root/work/pi-model-limit-evidence/`. No credentials are included.

Provider documentation checks used the combined research tool (TinyFish free + DuckDuckGo + social search), with top-page fetching. Provider-specific searches found no relevant web documentation. Public pages checked: https://xingchiapi.com (its configuration has an empty `doc_url`), https://api.xingchiapi.com, https://tokenlab.amd.com, https://tokenlab.amd.com/docs, https://mosi.cn, https://mosi.cn/docs, https://api.mosi.cn, https://howtofix.id, https://howtofix.id/docs, https://howtofix.id/pricing and https://api.howtofix.id. These fetches exposed no model-specific numeric limits; some returned empty pages or JavaScript shells, so documentation verification remains incomplete. No limit was inferred from model names, other vendors, parameter support, or test success.

Applied `/root/.pi/agent/models.json` with explicit contextWindow/maxTokens for all five models, preserving provider IDs, APIs, base URLs, model IDs and environment-variable references. Applied `/root/.pi/agent/settings.json` exactly as requested, including the 65536 reserve override for xingchi/gpt-6.1-sol. Parsed settings equality check: PASS.

Reload/reselection and reply test: started a fresh Pi process after applying files with `pi --model xingchi/gpt-6.1-sol --print 'Reply with exactly: PI_TEST_OK'`. This reloads configuration and explicitly selects the requested model in that process. Exit status **0**, stdout **PI_TEST_OK**, stderr empty. Replies work with the applied configuration. The existing interactive session was not programmatically reselected. This short test verifies connectivity and replies, not context/output capacity.
