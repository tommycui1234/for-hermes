#!/usr/bin/env python3
"""Auto-install token-usage footer patches into Hermes core.

This script is idempotent — running it multiple times is safe.
It creates .bak backups before modifying any file.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def find_hermes_agent_dir() -> Path:
    """Locate the hermes-agent source directory."""
    try:
        import hermes_cli
        base = Path(hermes_cli.__file__).resolve().parent.parent
        if (base / "run_agent.py").exists():
            return base
    except Exception:
        pass

    fallback = Path.home() / ".hermes" / "hermes-agent"
    if (fallback / "run_agent.py").exists():
        return fallback

    raise RuntimeError(
        "Could not locate hermes-agent directory. "
        "Please run this script from inside the Hermes environment."
    )


def backup(path: Path) -> Path:
    bak = path.with_suffix(path.suffix + ".bak")
    if not bak.exists():
        shutil.copy2(path, bak)
    return bak


def patch_run_agent(filepath: Path) -> bool:
    text = filepath.read_text()
    if "_turn_start_prompt_tokens" in text:
        print("  ✓ run_agent.py already patched")
        return True

    # 1. Insert turn start counters after api_call_count = 0
    anchor1 = "        api_call_count = 0\n"
    insert1 = (
        "        api_call_count = 0\n"
        "        _turn_start_prompt_tokens = self.session_prompt_tokens\n"
        "        _turn_start_completion_tokens = self.session_completion_tokens\n"
        "        _turn_start_total_tokens = self.session_total_tokens\n"
    )
    if anchor1 not in text:
        print("  ✗ Could not find anchor 'api_call_count = 0' in run_agent.py")
        return False
    text = text.replace(anchor1, insert1, 1)

    # 2. Insert turn deltas into the result dict
    anchor2 = '            "total_tokens": self.session_total_tokens,\n'
    insert2 = (
        '            "total_tokens": self.session_total_tokens,\n'
        '            "turn_prompt_tokens": self.session_prompt_tokens - _turn_start_prompt_tokens,\n'
        '            "turn_completion_tokens": self.session_completion_tokens - _turn_start_completion_tokens,\n'
        '            "turn_total_tokens": self.session_total_tokens - _turn_start_total_tokens,\n'
    )
    if anchor2 not in text:
        print("  ✗ Could not find anchor 'total_tokens' result dict in run_agent.py")
        return False
    text = text.replace(anchor2, insert2, 1)

    backup(filepath)
    filepath.write_text(text)
    print("  ✓ run_agent.py patched")
    return True


def patch_config(filepath: Path) -> bool:
    text = filepath.read_text()
    if '"show_token_usage"' in text:
        print("  ✓ hermes_cli/config.py already patched")
        return True

    anchor = '        "show_reasoning": False,\n'
    insert = '        "show_reasoning": False,\n        "show_token_usage": False,\n'
    if anchor not in text:
        print("  ✗ Could not find anchor 'show_reasoning' in hermes_cli/config.py")
        return False

    backup(filepath)
    text = text.replace(anchor, insert, 1)
    filepath.write_text(text)
    print("  ✓ hermes_cli/config.py patched")
    return True


def patch_cli(filepath: Path) -> bool:
    text = filepath.read_text()
    if "turn_prompt_tokens" in text and 'CLI_CONFIG.get("display", {}).get("show_token_usage")' in text:
        print("  ✓ cli.py already patched")
        return True

    # 1. Insert footer builder after response_previewed line
    anchor1 = (
        '            response_previewed = result.get("response_previewed", False) if result else False\n'
    )
    insert1 = (
        '            response_previewed = result.get("response_previewed", False) if result else False\n\n'
        '            # Build token-usage footer if enabled\n'
        '            _token_footer = ""\n'
        '            if result and CLI_CONFIG.get("display", {}).get("show_token_usage"):\n'
        '                _t_in = result.get("turn_prompt_tokens", 0)\n'
        '                _t_out = result.get("turn_completion_tokens", 0)\n'
        '                _t_total = result.get("turn_total_tokens", 0)\n'
        '                _t_model = result.get("model", self.model) or "unknown"\n'
        '                _token_footer = f"\\n\\n---\\n📊 Tokens: ↑{_t_in:,} ↓{_t_out:,} | Total: {_t_total:,} | Model: {_t_model}"\n'
    )
    if anchor1 not in text:
        print("  ✗ Could not find anchor 'response_previewed' in cli.py")
        return False
    text = text.replace(anchor1, insert1, 1)

    # 2a. TTS streaming: append footer after box close
    anchor2a = (
        "                if use_streaming_tts and _streaming_box_opened and not is_error_response:\n"
        "                    # Text was already printed sentence-by-sentence; just close the box\n"
        "                    w = shutil.get_terminal_size().columns\n"
        "                    _cprint(f\"\\n{_ACCENT}╯{'─' * (w - 2)}╭{_RST}\")\n"
    )
    insert2a = (
        "                if use_streaming_tts and _streaming_box_opened and not is_error_response:\n"
        "                    # Text was already printed sentence-by-sentence; just close the box\n"
        "                    w = shutil.get_terminal_size().columns\n"
        "                    _cprint(f\"\\n{_ACCENT}╯{'─' * (w - 2)}╭{_RST}\")\n"
        "                    if _token_footer:\n"
        "                        _cprint(_token_footer)\n"
    )
    if anchor2a in text:
        text = text.replace(anchor2a, insert2a, 1)
    else:
        print("  ! Could not find TTS streaming anchor in cli.py (skipping)")

    # 2b. Token streaming: append footer after box close
    anchor2b = (
        "                elif already_streamed:\n"
        "                    # Response was already streamed token-by-token with box framing;\n"
        "                    # _flush_stream() already closed the box. Skip Rich Panel.\n"
    )
    insert2b = (
        "                elif already_streamed:\n"
        "                    # Response was already streamed token-by-token with box framing;\n"
        "                    # _flush_stream() already closed the box. Skip Rich Panel.\n"
        "                    if _token_footer:\n"
        "                        _cprint(_token_footer)\n"
    )
    if anchor2b in text:
        text = text.replace(anchor2b, insert2b, 1)
    else:
        print("  ! Could not find token streaming anchor in cli.py (skipping)")

    # 2c. Non-streaming: add footer to Panel
    anchor2c = '                        _rich_text_from_ansi(response),\n'
    insert2c = '                        _rich_text_from_ansi(response + _token_footer),\n'
    # We need to target the specific Panel inside the response block.
    # A safer anchor is the surrounding Panel call.
    anchor2c_alt = (
        "                    _chat_console.print(Panel(\n"
        "                        _rich_text_from_ansi(response),\n"
    )
    insert2c_alt = (
        "                    _chat_console.print(Panel(\n"
        "                        _rich_text_from_ansi(response + _token_footer),\n"
    )
    if anchor2c_alt in text:
        text = text.replace(anchor2c_alt, insert2c_alt, 1)
    else:
        print("  ✗ Could not find non-streaming Panel anchor in cli.py")
        return False

    backup(filepath)
    filepath.write_text(text)
    print("  ✓ cli.py patched")
    return True


def patch_gateway(filepath: Path) -> bool:
    text = filepath.read_text()
    if "_rds_token" in text:
        print("  ✓ gateway/run.py already patched")
        return True

    # Insert footer logic before the streaming media block
    anchor = (
        "            # If streaming already delivered the response, extract and\n"
        "            # deliver any MEDIA: files before returning None.  Streaming\n"
    )
    insert = (
        "            # Append token usage footer if enabled (before streaming check so\n"
        "            # non-streaming responses include it without affecting TTS).\n"
        "            _token_footer = \"\"\n"
        "            if response:\n"
        "                try:\n"
        "                    from gateway.display_config import resolve_display_setting as _rds_token\n"
        "                    _show_tokens = _rds_token(\n"
        "                        _load_gateway_config(),\n"
        "                        _platform_config_key(source.platform),\n"
        '                        "show_token_usage",\n'
        "                        False,\n"
        "                    )\n"
        '                    logger.debug("token footer _show_tokens=%s for platform=%s", _show_tokens, source.platform)\n'
        "                    if _show_tokens:\n"
        '                        _t_in = agent_result.get("turn_prompt_tokens", 0)\n'
        '                        _t_out = agent_result.get("turn_completion_tokens", 0)\n'
        '                        _t_total = agent_result.get("turn_total_tokens", 0)\n'
        '                        _t_model = agent_result.get("model", "unknown")\n'
        '                        _token_footer = f"\\n\\n---\\n*📊 Tokens: ↑{_t_in:,} ↓{_t_out:,} | Total: {_t_total:,} | Model: {_t_model}*"\n'
        "                        response += _token_footer\n"
        '                        logger.debug("token footer appended: %s", _token_footer)\n'
        "                except Exception as _token_footer_err:\n"
        '                    logger.debug("token footer append failed: %s", _token_footer_err)\n'
        "\n"
        "            # If streaming already delivered the response, extract and\n"
        "            # deliver any MEDIA: files before returning None.  Streaming\n"
    )
    if anchor not in text:
        print("  ✗ Could not find streaming-media anchor in gateway/run.py")
        return False
    text = text.replace(anchor, insert, 1)

    # Insert footer follow-up inside the already_sent block
    anchor2 = (
        "                    # Streaming already delivered the main text; send the\n"
        "                    # token footer as a separate follow-up message so it\n"
        "                    # still appears at the end of the reply.\n"
    )
    # If this section already exists, skip. Otherwise add it.
    if anchor2 not in text:
        anchor2_target = (
            "                    # Streaming already delivered the main text; send the\n"
            "                    # reasoning separately so it still appears at the end.\n"
        )
        # There may not be a reasoning section; try another anchor.
        anchor2_target_alt = (
            "                if response:\n"
            "                    _media_adapter = self.adapters.get(source.platform)\n"
        )
        insert2 = (
            "                if response:\n"
            "                    _media_adapter = self.adapters.get(source.platform)\n"
            "                    if _media_adapter:\n"
            "                        await self._deliver_media_from_response(\n"
            "                            response, event, _media_adapter,\n"
            "                        )\n"
            "                    # Streaming already delivered the main text; send the\n"
            "                    # token footer as a separate follow-up message so it\n"
            "                    # still appears at the end of the reply.\n"
            "                    if _token_footer:\n"
            "                        _footer_adapter = self.adapters.get(source.platform)\n"
            "                        if _footer_adapter:\n"
            "                            try:\n"
            '                                _thread_meta = {"thread_id": event.source.thread_id} if event.source.thread_id else None\n'
            "                                await _footer_adapter.send(\n"
            "                                    event.source.chat_id,\n"
            "                                    _token_footer,\n"
            "                                    metadata=_thread_meta,\n"
            "                                )\n"
            "                            except Exception:\n"
            "                                pass\n"
        )
        if anchor2_target_alt in text:
            text = text.replace(anchor2_target_alt, insert2, 1)
        else:
            print("  ! Could not find already_sent media anchor in gateway/run.py (footer follow-up skipped)")

    backup(filepath)
    filepath.write_text(text)
    print("  ✓ gateway/run.py patched")
    return True


def patch_display_config(filepath: Path) -> bool:
    """Ensure show_token_usage exists in gateway/display_config.py defaults."""
    text = filepath.read_text()
    if '"show_token_usage"' in text:
        print("  ✓ gateway/display_config.py already patched")
        return True

    # Insert into _GLOBAL_DEFAULTS
    anchor = '    "streaming": None,  # None = follow top-level streaming config\n'
    insert = '    "show_token_usage": False,\n'
    if anchor not in text:
        print("  ! Could not find anchor in gateway/display_config.py (skipping)")
        return True  # non-critical

    backup(filepath)
    text = text.replace(anchor, anchor + insert, 1)

    # Also insert into tier dicts
    for tier in ("_TIER_HIGH", "_TIER_MEDIUM", "_TIER_LOW", "_TIER_MINIMAL"):
        anchor_tier = f"{tier} = {{\n"
        if anchor_tier in text and '"show_token_usage"' not in text.split(anchor_tier, 1)[1].split("\n}", 1)[0]:
            # Find the last line before the closing brace in this tier block
            # Simpler: insert after streaming line in each tier
            tier_anchor = f'        "streaming": None,  # follow global\n'
            tier_insert = '        "show_token_usage": False,\n'
            # We must be careful to only replace inside the specific tier.
            # Since tiers are sequential, we can use a limit of 1 per tier.
            parts = text.split(tier_anchor, 1)
            if len(parts) == 2:
                text = parts[0] + tier_anchor + tier_insert + tier_anchor.join(parts[1:])

    filepath.write_text(text)
    print("  ✓ gateway/display_config.py patched")
    return True


def main() -> int:
    print("🔧 Token Usage Monitoring Installer")
    print("-" * 40)

    try:
        base = find_hermes_agent_dir()
    except RuntimeError as e:
        print(f"✗ {e}")
        return 1

    print(f"Found Hermes at: {base}\n")

    results = []
    files = {
        "run_agent.py": base / "run_agent.py",
        "hermes_cli/config.py": base / "hermes_cli" / "config.py",
        "cli.py": base / "cli.py",
        "gateway/run.py": base / "gateway" / "run.py",
        "gateway/display_config.py": base / "gateway" / "display_config.py",
    }

    for name, path in files.items():
        print(f"Patching {name} ...")
        if not path.exists():
            print(f"  ✗ File not found: {path}")
            results.append(False)
            continue

        if name == "run_agent.py":
            results.append(patch_run_agent(path))
        elif name == "hermes_cli/config.py":
            results.append(patch_config(path))
        elif name == "cli.py":
            results.append(patch_cli(path))
        elif name == "gateway/run.py":
            results.append(patch_gateway(path))
        elif name == "gateway/display_config.py":
            results.append(patch_display_config(path))

    print("-" * 40)
    if all(results):
        print("✅ All patches applied successfully.")
        print("\nNext steps:")
        print("  1. Set 'display.show_token_usage: true' in ~/.hermes/config.yaml")
        print("  2. Restart the gateway if you use messaging platforms.")
        return 0
    else:
        print("⚠ Some patches failed. Check the output above.")
        print("If your Hermes version is different, you may need to apply the changes manually")
        print("using the instructions in SKILL.md.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
