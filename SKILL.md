---
name: token-usage-monitoring
description: Add a real-time token-usage footer to every Hermes response in CLI and Gateway by modifying the agent core and display layers.
category: devops
---

# Token Usage Monitoring

Add a real-time token-usage footer to every Hermes response in CLI and Gateway.

## Trigger

User asks any of the following:
- "Show token usage after every reply"
- "Add token footer like OpenClaw"
- "How do I display prompt/completion tokens?"
- "Install token usage monitoring"
- Any request referencing tokens, costs, or usage display

## Quick Start (Auto-Install)

After this skill is loaded, run the provided install script to patch the Hermes core automatically:

```bash
# Activate the Hermes virtual environment first if you use one
source ~/.hermes/hermes-agent/venv/bin/activate

# Install
python ~/.hermes/skills/token-usage-monitoring/scripts/install.py

# Enable in config
hermes config set display.show_token_usage true

# Restart gateway (if you use Feishu/Telegram/Discord/etc.)
hermes gateway restart
```

To remove the patches later:

```bash
python ~/.hermes/skills/token-usage-monitoring/scripts/uninstall.py
```

## Context

Hermes already tracks cumulative token usage inside `AIAgent` (`run_agent.py`). The challenge is exposing **per-turn** deltas without polluting transcripts, TTS, or API responses.

## Design Principle

**Never mutate `final_response` inside `run_agent.py`.** Doing so pollutes the transcript, causes TTS to read token numbers aloud, and breaks API-server consumers that expect clean JSON. Always append at the display layer (`cli.py` / `gateway/run.py`).

## Step-by-Step (Manual)

If the auto-install script fails because your Hermes version differs, apply these four changes manually.

### 1. Compute turn-level token deltas in `run_agent.py`

At the top of `run_conversation()`, just after `api_call_count = 0`, snapshot the cumulative counters:

```python
        api_call_count = 0
        _turn_start_prompt_tokens = self.session_prompt_tokens
        _turn_start_completion_tokens = self.session_completion_tokens
        _turn_start_total_tokens = self.session_total_tokens
```

At the bottom, in the `result` dict returned by `run_conversation()`, add the delta fields:

```python
            "prompt_tokens": self.session_prompt_tokens,
            "completion_tokens": self.session_completion_tokens,
            "total_tokens": self.session_total_tokens,
            "turn_prompt_tokens": self.session_prompt_tokens - _turn_start_prompt_tokens,
            "turn_completion_tokens": self.session_completion_tokens - _turn_start_completion_tokens,
            "turn_total_tokens": self.session_total_tokens - _turn_start_total_tokens,
```

**Why deltas?** A single user turn may involve multiple API calls (tool-calling loops). Session counters are cumulative, so subtracting the baseline gives the true cost of *this request*.

### 1b. Fallback for providers that omit `usage` data

Some providers (notably Chinese endpoints in streaming mode) return `response.usage = None`. Without this fallback, session counters never increment and turn deltas will always be 0.

Find the block in `run_agent.py` that checks `hasattr(response, 'usage') and response.usage:` (usually inside the response handling loop). Insert a rough estimation **before** the existing check:

```python
                    # Track actual token usage from response for context management
                    # Some providers (e.g. Chinese endpoints in streaming mode) omit
                    # usage data. Inject a rough estimate so counters still work.
                    if not (hasattr(response, 'usage') and response.usage):
                        from agent.model_metadata import estimate_tokens_rough
                        _resp_content = ""
                        if hasattr(response, 'choices') and response.choices:
                            _msg = response.choices[0].message
                            _resp_content = getattr(_msg, 'content', '') or ''
                        _completion = estimate_tokens_rough(_resp_content)
                        _prompt_texts = []
                        for m in messages[:-1]:
                            if isinstance(m, dict):
                                _prompt_texts.append(m.get('content', '') or '')
                            elif hasattr(m, 'content'):
                                _prompt_texts.append(m.content or '')
                        _prompt = estimate_tokens_rough("\n".join(_prompt_texts))
                        class _FakeUsage:
                            prompt_tokens = _prompt
                            completion_tokens = _completion
                            total_tokens = _prompt + _completion
                        response.usage = _FakeUsage()

                    if hasattr(response, 'usage') and response.usage:
                        # ... existing usage tracking logic ...
```

### 2. Add a config gate in `hermes_cli/config.py`

Insert under `DEFAULT_CONFIG["display"]`:

```python
        "show_token_usage": False,
```

Bump `_config_version` so existing configs migrate automatically.

### 3. Append the footer in `cli.py`

Find the block that prints the response (around the `Panel(... _rich_text_from_ansi(response) ...)` call). Build the footer string when the display config flag is true:

```python
            # Build token-usage footer if enabled
            _token_footer = ""
            if result and CLI_CONFIG.get("display", {}).get("show_token_usage"):
                _t_in = result.get("turn_prompt_tokens", 0)
                _t_out = result.get("turn_completion_tokens", 0)
                _t_total = result.get("turn_total_tokens", 0)
                _t_model = result.get("model", self.model) or "unknown"
                _token_footer = f"\n\n---\n📊 Tokens: ↑{_t_in:,} ↓{_t_out:,} | Total: {_t_total:,} | Model: {_t_model}"
```

Then append `_token_footer` wherever the response is rendered:

- **Non-streaming / Rich Panel**: `_rich_text_from_ansi(response + _token_footer)`
- **Streaming already rendered**: print `_token_footer` after the stream box closes
- **Streaming TTS**: print `_token_footer` after the TTS box closes

### 4. Append the footer in `gateway/run.py`

In `_handle_message_with_agent()`, after `agent_result` is returned but **before** the `already_sent` streaming guard, resolve the per-platform display setting and append:

```python
            # Append token usage footer if enabled (before streaming check so
            # non-streaming responses include it without affecting TTS).
            _token_footer = ""
            if response:
                try:
                    from gateway.display_config import resolve_display_setting as _rds_token
                    _show_tokens = _rds_token(
                        _load_gateway_config(),
                        _platform_config_key(source.platform),
                        "show_token_usage",
                        False,
                    )
                    if _show_tokens:
                        _t_in = agent_result.get("turn_prompt_tokens", 0)
                        _t_out = agent_result.get("turn_completion_tokens", 0)
                        _t_total = agent_result.get("turn_total_tokens", 0)
                        _t_model = agent_result.get("model", "unknown")
                        _token_footer = f"\n\n---\n*📊 Tokens: ↑{_t_in:,} ↓{_t_out:,} | Total: {_t_total:,} | Model: {_t_model}*"
                        response += _token_footer
                except Exception:
                    pass
```

This ensures the footer is added **after** the agent finishes but **before** the message is delivered to the platform adapter, so it appears in Feishu/Telegram/Discord/etc.

For streaming paths, send the footer as a follow-up message if the main text was already streamed:

```python
                    if _token_footer:
                        _footer_adapter = self.adapters.get(source.platform)
                        if _footer_adapter:
                            try:
                                _thread_meta = {"thread_id": event.source.thread_id} if event.source.thread_id else None
                                await _footer_adapter.send(
                                    event.source.chat_id,
                                    _token_footer,
                                    metadata=_thread_meta,
                                )
                            except Exception:
                                pass
```

## Enable for the User

After patching, set in `~/.hermes/config.yaml`:

```yaml
display:
  show_token_usage: true
```

For per-platform control (e.g. only Feishu):

```yaml
display:
  show_token_usage: false
  platforms:
    feishu:
      show_token_usage: true
```

Then restart the gateway if you use messaging platforms.

## Pitfalls

1. **Never mutate `final_response` inside `run_agent.py`.** Always append at the display layer.
2. **Use turn-level deltas, not session totals.** Session totals grow monotonically and would confuse users.
3. **Gateway per-platform overrides require `resolve_display_setting`.** Do not read the global config key directly; that ignores `display.platforms.<platform>` overrides.
4. **Place the gateway append before the `already_sent` / streaming checks.** Otherwise streaming responses skip the footer entirely.
5. **Always bump `_config_version`.** Without it, existing user configs will lack the new key and the feature stays off silently.
6. **Auto-installer idempotency must check ALL patch elements.** If the install script only checks for the first insertion point (e.g., `_turn_start_prompt_tokens`), a partially-patched file from an earlier failed run will be falsely skipped. This can manifest as `turn_prompt_tokens` working but `turn_total_tokens` staying at 0. Verify every patched symbol before returning "already patched".
7. **Chinese streaming providers may omit `usage` data.** If the token footer consistently shows `📊 Tokens: ↑0 ↓0 | Total: 0`, the provider likely skips `response.usage`. Add the `_FakeUsage` fallback using `estimate_tokens_rough` so the counters remain functional.

## Testing Checklist

- `python -m pytest tests/test_model_tools.py -q`
- `python -m pytest tests/run_agent/test_agent_loop.py -q`
- `python -m pytest tests/run_agent/test_context_token_tracking.py -q`
- Send a message via CLI with `show_token_usage: true` and verify the footer appears below the response box.
- Send a message via Gateway (e.g. Feishu) and verify the footer appears in the chat bubble.
