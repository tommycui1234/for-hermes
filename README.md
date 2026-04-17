# Token Usage Monitoring

A [Hermes](https://github.com/tommyc/hermes-agent) skill that appends a real-time **token-usage footer** to every assistant response in both CLI and Gateway (Feishu, Telegram, Discord, Slack, etc.).

---

## ✨ What it does

After enabling, every reply ends with a concise footer like:

```markdown
---
📊 Tokens: ↑1,234 ↓567 | Total: 1,801 | Model: kimi-for-coding
```

- **↑** = prompt (input) tokens for this turn
- **↓** = completion (output) tokens for this turn
- **Total** = combined turn-level cost
- **Model** = the model that served the response

---

## 🚀 Quick Start

### 1. Install the skill

```bash
hermes skills install https://github.com/YOUR_USERNAME/token-usage-monitoring
```

Or clone it manually into `~/.hermes/skills/token-usage-monitoring`.

### 2. Patch the Hermes core

Because token accounting lives deep in the agent loop, this skill patches **four core files**. An automated installer is provided:

```bash
# Make sure you're inside the Hermes venv if you use one
source ~/.hermes/hermes-agent/venv/bin/activate

python ~/.hermes/skills/token-usage-monitoring/scripts/install.py
```

The script is **idempotent** — running it twice is safe. Backups (`.bak`) are created automatically.

### 3. Enable in config

Edit `~/.hermes/config.yaml`:

```yaml
display:
  show_token_usage: true
```

You can also enable it per-platform:

```yaml
display:
  show_token_usage: false
  platforms:
    feishu:
      show_token_usage: true
```

### 4. Restart the gateway

```bash
hermes gateway restart
```

---

## 🔧 Files modified

| File | Change |
|------|--------|
| `run_agent.py` | Computes **turn-level** token deltas (`turn_prompt_tokens`, `turn_completion_tokens`, `turn_total_tokens`) |
| `hermes_cli/config.py` | Adds `display.show_token_usage` config flag (default `false`) |
| `cli.py` | Appends the footer before the response is rendered in the terminal |
| `gateway/run.py` | Appends the footer before the response is sent to messaging platforms |
| `gateway/display_config.py` | Adds `show_token_usage` to per-platform default tiers |

> **Design principle:** The footer is injected at the **display layer**, not inside `final_response`. This keeps transcripts, TTS, and API responses clean.

---

## 📝 Uninstall

To remove the patches and restore backups:

```bash
python ~/.hermes/skills/token-usage-monitoring/scripts/uninstall.py
```

Then restart the gateway.

---

## 🐛 Troubleshooting

### Installer says "Could not find anchor ..."

Your Hermes version may differ from the one this skill was written against. In that case, follow the **manual step-by-step instructions** inside [`SKILL.md`](./SKILL.md).

### Footer appears in CLI but not in Feishu/Telegram

Make sure you restarted the gateway after changing `config.yaml`.

---

## 📄 License

MIT
