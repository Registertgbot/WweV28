"""Ring-announcer entrance and live commentary. These are sent as their own messages, never inside a GIF caption."""
from __future__ import annotations

import random

from services import rules
from services.rules import Move

MAX_HP = 100

INTROS = [
    "Ladies and gentlemen, the following contest is scheduled for ONE FALL!",
    "The lights drop, the crowd is on its feet — this one is for bragging rights!",
    "Welcome to the arena! Two fighters, one winner, no mercy!",
    "The bell is about to ring and the whole building is buzzing!",
]
ENTRANCES = [
    "{n} walks down the ramp as the crowd goes wild!",
    "Pyro explodes and {n} storms to the ring!",
    "{n} slides into the ring and stares down the arena!",
    "The lights go out… and when they return, {n} is standing in the ring!",
    "{n} struts to the ring with total confidence!",
    "{n} climbs the turnbuckle and soaks up the cheers!",
]
OUTROS = ["🔔 <i>Ring the bell!</i>", "🔔 <i>Let's get it started!</i>", "🔔 <i>DING DING DING!</i>"]

FINISHER_KO = [
    "{a} hits the FINISHER… 1… 2… 3! {d} is down for good!",
    "That's it! {a} connects with the finisher and {d} will not get up!",
    "It's all over! {a} puts {d} away with the finisher!",
]
PLAIN_KO = [
    "{d} can't answer the count! {a} wins it!",
    "{a} lands the last blow and {d} is out cold!",
    "The referee waves it off — {a} takes the victory!",
]
FINISHER_HIT = [
    "THE FINISHER! {a} just hit it on {d} — is this the end?!",
    "Oh my! {a} unloads the finisher on {d}!",
    "{a} goes for the big one and it CONNECTS on {d}!",
]
REVERSED = [
    "What a counter! {d} turns {a}'s {m} around!",
    "{d} saw it coming and reverses the {m}!",
    "Reversal! {a} walked right into it!",
    "The crowd gasps — {d} flips the script on {a}!",
]
FAILED_REVERSAL = [
    "{d} tries to counter… too late! {a} lands the {m}!",
    "{d} guessed wrong and pays for it!",
    "No escape this time — {a} connects with the {m}!",
]
BIG_HIT = [
    "{a} nails the {m}! {d} is hurting!",
    "That {m} from {a} shook the whole arena!",
    "Huge {m}! {d} might feel that in the morning!",
]
SMALL_HIT = [
    "{a} with a quick {m} — {d} shakes it off.",
    "{a} keeps the pressure on with a {m}.",
    "A sharp {m} from {a}, but {d} is still in this.",
]
AUTO = ["{d} wasn't ready for that one!", "{d} hesitated and the move landed clean!"]
LOW_HP = ["{d} is hanging by a thread!", "{d} is barely standing!", "One more big hit and it's over for {d}!"]


def _fmt(pool: list[str], rng: random.Random, **names: str) -> str:
    return rng.choice(pool).format(**names)


def entrance_text(snap, esc, rng: random.Random | None = None) -> str:
    rng = rng or random
    a, b = (esc(p.name) for p in snap.players[:2])
    return ("🎤 <b>ENTRANCE</b>\n"
            f"<i>{rng.choice(INTROS)}</i>\n\n"
            f"🔊 {rng.choice(ENTRANCES).format(n=f'<b>{a}</b>')}\n"
            f"🔊 {rng.choice(ENTRANCES).format(n=f'<b>{b}</b>')}\n\n"
            f"{rng.choice(OUTROS)}")


def turn_text(snap, turn, esc, rng: random.Random | None = None) -> str:
    """One or two lines of commentary for a resolved turn."""
    rng = rng or random
    att, dfn = snap.player(turn.attacker_id), snap.player(turn.defender_id)
    names = {"a": f"<b>{esc(att.name)}</b>", "d": f"<b>{esc(dfn.name)}</b>", "m": rules.MOVE_NAMES[Move(turn.move)]}
    if turn.finished:
        pool = FINISHER_KO if turn.move == Move.FINISHER.value and not turn.reversed else PLAIN_KO
        if turn.reversed:                                              # the counter finished the attacker
            names["a"], names["d"] = names["d"], names["a"]
        return f"🎙️ {_fmt(pool, rng, **names)}"
    if turn.reversed:
        line = _fmt(REVERSED, rng, **names)
    elif turn.reversal_attempted:
        line = _fmt(FAILED_REVERSAL, rng, **names)
    elif turn.move == Move.FINISHER.value:
        line = _fmt(FINISHER_HIT, rng, **names)
    elif turn.damage_to_defender >= 25:
        line = _fmt(BIG_HIT, rng, **names)
    elif turn.auto:
        line = _fmt(AUTO, rng, **names)
    else:
        line = _fmt(SMALL_HIT, rng, **names)
    victim = att if turn.reversed else dfn
    if 0 < victim.hp <= 20:
        v = f"<b>{esc(victim.name)}</b>"
        line += "\n" + _fmt(LOW_HP, rng, a=v, d=v, m="")
    return f"🎙️ {line}"
