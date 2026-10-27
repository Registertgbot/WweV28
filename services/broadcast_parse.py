"""Parsing of the owner's broadcast commands (pure functions, no Telegram, no database).

    /broadcast [target] [pin] [silent] [at=9:30pm | in=45m] [repeat=daily|weekly] [reward=500]
    btn: Label|https://link ; Other|https://link        (one line per button row, optional)
    message text ...                                    (only when you do not reply to a message)

Targets: groups, users, all, vip, champions, collectors, players, chat:<id>, ids:1,2,3
"""
from __future__ import annotations

import json

TARGET_WORDS = ("groups", "users", "all", "vip", "champions", "collectors", "players")


def parse_command(args: str | None, default_kind: str = "all") -> dict:
    lines = (args or "").split("\n")
    out = {"kind": default_kind, "pin": False, "silent": False, "at": None, "repeat": None, "reward": 0,
           "buttons": [], "text": "", "error": None}
    head, rest = lines[0].split(), lines[1:]
    first_text = ""
    for i, tok in enumerate(head):
        low = tok.lower()
        if low in TARGET_WORDS or low.startswith(("chat:", "ids:")):
            out["kind"] = low
        elif low in ("pin", "silent"):
            out[low] = True
        elif low.startswith("at="):
            out["at"] = tok[3:].replace("_", " ")
        elif low.startswith("in="):
            out["at"] = "+" + tok[3:]
        elif low.startswith("repeat="):
            if low[7:] not in ("daily", "weekly"):
                out["error"] = "repeat= must be daily or weekly."
            out["repeat"] = low[7:]
        elif low.startswith("reward="):
            if not low[7:].isdigit() or not 0 < int(low[7:]) <= 100000:
                out["error"] = "reward= must be a number of coins between 1 and 100000."
            else:
                out["reward"] = int(low[7:])
        else:
            first_text = " ".join(head[i:])
            break
    body = [first_text] if first_text else []
    for line in rest:
        if line.strip().lower().startswith("btn:"):
            row = []
            for part in line.split(":", 1)[1].split(";"):
                label, _, url = part.partition("|")
                label, url = label.strip(), url.strip()
                if label and url.startswith(("http://", "https://", "tg://")):
                    row.append([label[:40], url])
                elif part.strip():
                    out["error"] = f"Button “{part.strip()[:30]}” needs the form Label|https://link"
            if row:
                out["buttons"].append(row)
        else:
            body.append(line)
    out["text"] = "\n".join(body).strip()
    if out["repeat"] and not out["at"]:
        out["error"] = out["error"] or "repeat= needs a start time, e.g. at=9pm."
    return out


def parse_poll(text: str) -> dict | None:
    """'Question | A | *B | C' -> {q, options, correct}; a leading * marks the correct answer (makes it a quiz)."""
    parts = [p.strip() for p in text.split("|") if p.strip()]
    if len(parts) < 3 or len(parts) > 11:
        return None
    options, correct = [], None
    for i, opt in enumerate(parts[1:]):
        if opt.startswith("*"):
            correct, opt = i, opt[1:].strip()
        options.append(opt[:100])
    return {"q": parts[0][:290], "options": options, "correct": correct}


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)
