#!/usr/bin/env python3
"""Comprueba que cada nivel se pueda terminar con un bot.

El bot imita a una persona: decide una vez cada fotograma (60 Hz) y la
fisica corre a 240 Hz.  Cada modo tiene su propia politica:

- cubo: salta en el ultimo momento seguro y pulsa los orbes al tocarlos.
- nave: control predictivo que apunta al centro del hueco libre.
- bola: gira la gravedad cuando se acerca un pincho de su superficie.

Sirve para detectar niveles imposibles tras tocar la fisica, los hitboxes
o el diseno.

Uso:  .venv/bin/python verify.py [--verbose]
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from levels import GROUND_Y, LEVELS, TILE  # noqa: E402
from main import (HIT, ORB_R, STEP, MODE_BALL, MODE_SHIP, LAVA_Y,  # noqa: E402
                  LevelData, Sim, circle_hits_rect, clamp)

FRAME = 1.0 / 60.0  # el juego decide una vez por fotograma
SUB = 4             # pasos de fisica por fotograma (240 Hz)
ROLLOUT = 0.80      # segundos maximos simulados por salto
SETTLE = 18         # pasos extra tras aterrizar
BALL_REACH = 158.0  # distancia a la que la bola gira antes de un pincho
SHIP_LOOK = 175.0   # anticipacion del piloto de la nave
SHIP_PRED = 0.11    # segundos de prediccion de la velocidad vertical


def clone(sim):
    c = Sim.__new__(Sim)
    c.data = sim.data
    c.mode = sim.mode
    c.x = sim.x
    c.y = sim.y
    c.hit_w = sim.hit_w
    c.hit_h = sim.hit_h
    c.vy = sim.vy
    c.gdir = sim.gdir
    c.on_ground = sim.on_ground
    c.alive = True
    c.finished = False
    c.ang = sim.ang
    c.events = []
    c.cause = None
    c.used_orbs = set(sim.used_orbs)
    c.used_pads = set(sim.used_pads)
    c.next_portal = sim.next_portal
    c.last_orb = sim.last_orb
    c.t = sim.t
    return c


def frame(sim, held, pressed):
    """Un fotograma completo: 4 pasos de fisica, pulsacion solo en el primero."""
    for i in range(SUB):
        sim.step(STEP, held, pressed and i == 0)
        if not sim.alive or sim.finished:
            return


def orb_touch(sim):
    """Indice del orbe sin usar que toca al jugador, o None."""
    hx = sim.x + HIT
    hy = sim.y + HIT
    hw = sim.hit_w - 2.0 * HIT
    hh = sim.hit_h - 2.0 * HIT
    for ox, oy, _kind, idx in sim.data.orbs_near(sim.x):
        if idx in sim.used_orbs:
            continue
        if circle_hits_rect(ox, oy, ORB_R, hx, hy, hw, hh):
            return idx
    return None


# --------------------------------------------------------------------------- #
# Cubo
# --------------------------------------------------------------------------- #

def cube_rollout(sim, pressed):
    """Salta (o pulsa el orbe) y comprueba que sobrevive al aterrizaje."""
    s = clone(sim)
    frame(s, True, pressed)
    t = FRAME
    while t < ROLLOUT and s.alive and not s.finished and not s.on_ground:
        auto = orb_touch(s) is not None
        frame(s, auto, auto)
        t += FRAME
    if not (s.alive or s.finished):
        return False
    if s.finished:
        return True
    for _ in range(SETTLE):
        s.step(STEP, False, False)
        if not s.alive:
            return False
        if s.finished:
            return True
    return True


def gap_ahead(sim, data, dist=190.0):
    """True si el suelo solido termina a menos de ``dist`` px."""
    edge = sim.x + sim.hit_w
    for a, _b in data.pits:
        if 0.0 < a - edge < dist:
            return True
    return False


def footing_ahead(sim, data, dist=78.0):
    """True si hay suelo o una losa bajo los pies un poco mas adelante."""
    probe = sim.x + sim.hit_w + dist
    feet = sim.y + sim.hit_h
    if not data.over_pit(probe, 0.0):
        return True
    for r in data.blocks_near(sim.x):
        if r.left - 10 <= probe <= r.right + 10 and abs(r.top - feet) <= 14:
            return True
    return False


def obstacle_close(sim, data, dist=300.0):
    px = sim.x
    for b in data.blocks_near(px):
        if 0 < b.left - px < dist:
            return True
    for r in data.hazards_near(px, reach=dist + 80):
        if 0 < r.left - px < dist:
            return True
    for cx, cy, rad, amp in data.saws_at(px, sim.t):
        if 0 < (cx - rad) - px < dist:
            return True
    return False


def cube_policy(sim, data, prev_held):
    # orbe al alcance: se pulsa de inmediato (el orbe se activa al mantener)
    if not sim.on_ground and orb_touch(sim) is not None:
        return True

    if not sim.on_ground or prev_held:
        return False
    if (not obstacle_close(sim, data) and not gap_ahead(sim, data)
            and footing_ahead(sim, data)):
        return False
    if not cube_rollout(sim, True):
        return False
    # si saltar un fotograma despues tambien sirve, esperamos
    s = clone(sim)
    frame(s, False, False)
    if s.alive and not s.finished:
        return not cube_rollout(s, True)
    return True


# --------------------------------------------------------------------------- #
# Nave
# --------------------------------------------------------------------------- #

def ship_policy(sim, data, prev_held):
    h = sim.hit_h
    x0 = sim.x
    x1 = sim.x + sim.hit_w + SHIP_LOOK
    top, bottom = 0.0, float(GROUND_Y)

    for r in data.blocks_near(sim.x):
        if r.right <= x0 or r.left >= x1:
            continue
        if r.bottom <= 440:
            top = max(top, float(r.bottom))
        elif r.top >= 440:
            bottom = min(bottom, float(r.top))

    for cx, cy, rad, amp in data.saws_at(sim.x, sim.t):
        # Una sierra movil barre toda su amplitud: la evitamos entera.
        if cx + rad + amp <= x0 or cx - rad - amp >= x1:
            continue
        if cy < 440:
            top = max(top, cy + rad + amp)
        else:
            bottom = min(bottom, cy - rad - amp)

    lo = top + h / 2.0 + 5.0
    hi = bottom - h / 2.0 - 5.0
    mid = (top + bottom) / 2.0
    target = mid if lo > hi else clamp(mid, lo, hi)

    pred = sim.y + h / 2.0 + sim.vy * SHIP_PRED
    if pred > target + 4.0:
        return True
    if pred < target - 4.0:
        return False
    return prev_held


# --------------------------------------------------------------------------- #
# Bola
# --------------------------------------------------------------------------- #

def ball_flip_safe(sim):
    """Gira ahora y comprueba que no aterriza sobre un pincho."""
    s = clone(sim)
    frame(s, True, True)
    t = FRAME
    landed_at = None
    while t < 0.75 and s.alive and not s.finished:
        if landed_at is not None and t > landed_at + 0.12:
            break
        s.step(STEP, False, False)
        if s.on_ground and landed_at is None:
            landed_at = t
        t += STEP
    return s.alive or s.finished


def ball_policy(sim, data, prev_held):
    if not sim.on_ground or prev_held:
        return False

    # En el suelo, saltar al techo antes de un vacio con lava.
    if (sim.gdir > 0 and gap_ahead(sim, data, BALL_REACH + 40)
            and ball_flip_safe(sim)):
        return True
    if sim.gdir > 0 and not footing_ahead(sim, data, BALL_REACH):
        return ball_flip_safe(sim)

    on_floor = sim.gdir > 0
    edge = sim.x + sim.hit_w
    nearest = None
    for r in data.hazards_near(sim.x, reach=BALL_REACH + 140):
        if r.left <= edge:
            continue
        floor_hazard = r.centery > 470
        if floor_hazard != on_floor:
            continue
        d = r.left - edge
        if nearest is None or d < nearest:
            nearest = d

    if nearest is None or nearest > BALL_REACH:
        return False
    return ball_flip_safe(sim)


# --------------------------------------------------------------------------- #
# Bucle
# --------------------------------------------------------------------------- #

def run(level, max_time=150.0, verbose=False):
    data = LevelData(level)
    sim = Sim(data)
    t = 0.0
    inputs = 0
    prev_held = False
    mode = sim.mode

    while t < max_time:
        if sim.mode != mode:
            mode = sim.mode
            if verbose:
                print(f"    modo {mode} en x={sim.x:.0f} (t={t:.1f}s)")
        if sim.mode == MODE_SHIP:
            held = ship_policy(sim, data, prev_held)
        elif sim.mode == MODE_BALL:
            held = ball_policy(sim, data, prev_held)
        else:
            held = cube_policy(sim, data, prev_held)

        pressed = held and not prev_held
        if held and not prev_held:
            inputs += 1
        frame(sim, held, pressed)
        prev_held = held
        t += FRAME

        if not sim.alive:
            return False, sim.x, sim.cause, t, inputs
        if sim.finished:
            return True, sim.x, None, t, inputs

    return False, sim.x, "timeout", t, inputs


def main():
    verbose = "--verbose" in sys.argv
    ok = True
    for lvl in LEVELS:
        good, x, cause, t, inputs = run(lvl, verbose=verbose)
        estado = "OK" if good else "FALLA"
        print(f"[{estado}] {lvl.name}: x={x:.0f}px (celda {x / TILE:.1f}), "
              f"causa={cause}, t={t:.1f}s, pulsaciones={inputs}")
        if not good:
            ok = False
            for o in lvl.objs:
                if abs(o.x - x) < 420:
                    print(f"    cerca: {o}  celda {o.x / TILE}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
