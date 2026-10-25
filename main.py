#!/usr/bin/env python3
"""Neon Dash: un clon de Geometry Dash hecho en Python + pygame para Linux.

Controles
---------
Espacio / flecha arriba / W / clic   saltar / impulsar la nave / girar la bola
R                                   reiniciar el intento
ESC                                 pausa / volver al menu
M                                   musica / sonido on-off
F11                                 pantalla completa
"""

from __future__ import annotations

import array
import bisect
import copy
import json
import math
import os
import random
import sys

import pygame

from levels import GROUND_Y, LEVELS, TILE

# --------------------------------------------------------------------------- #
# Ajustes
# --------------------------------------------------------------------------- #

W, H = 1280, 720
FPS = 60
STEP = 1.0 / 240.0

SPEED = 400.0
GRAVITY = 3400.0
JUMP_V = 780.0
PAD_V = 1320.0
SPAWN_X = 3.0 * TILE
LAVA_Y = GROUND_Y + 30      # superficie de la lava en los vacios
HIT = 5.0            # margen de perdon del cubo
JUMP_ROT = 540.0     # grados por segundo en el aire

MENU, PLAY, DEAD, WIN, PAUSE = range(5)

TITLE = "NEON DASH"


def clamp(v, a, b):
    return a if v < a else b if v > b else v


def hit(x, y, w, h, r):
    return x < r.right and x + w > r.left and y < r.bottom and y + h > r.top


def circle_hits_rect(cx, cy, radius, x, y, w, h):
    nx = clamp(cx, x, x + w)
    ny = clamp(cy, y, y + h)
    dx, dy = cx - nx, cy - ny
    return dx * dx + dy * dy <= radius * radius


# --------------------------------------------------------------------------- #
# Fuentes y texto
# --------------------------------------------------------------------------- #

def load_font(size, bold=False):
    for name in ("dejavusans", "liberationsans", "freesans", "notosans", "ubuntu"):
        path = pygame.font.match_font(name, bold=bold)
        if path:
            return pygame.font.Font(path, size)
    return pygame.font.Font(None, size)


def _blur(img, factor):
    """Desenfoca una superficie con alfa reduciendola y volviendola a escalar."""
    w, h = img.get_size()
    if factor <= 1 or w < 4 or h < 4:
        return img
    small = pygame.transform.smoothscale(img, (max(1, w // factor), max(1, h // factor)))
    return pygame.transform.smoothscale(small, (w, h))


def blit_text(surf, font, msg, color, pos, anchor="center", glow=None):
    img = font.render(msg, True, color)
    rect = img.get_rect(**{anchor: (int(pos[0]), int(pos[1]))})
    if glow:
        base = font.render(msg, True, glow)
        # el RGB de los pixeles transparentes es negro: lo pintamos del color
        # del brillo para que el desenfoque no deje un rectangulo oscuro.
        base.fill(glow, special_flags=pygame.BLEND_RGB_MAX)
        halo = _blur(base, 4)
        halo.set_alpha(140)
        surf.blit(halo, rect)
        wide = _blur(base, 8)
        wide.set_alpha(70)
        surf.blit(wide, rect)
        surf.blit(wide, rect)
    surf.blit(img, rect)
    return rect


# --------------------------------------------------------------------------- #
# Brillos pre-renderizados (se suman con BLEND_ADD)
# --------------------------------------------------------------------------- #

_GLOWS = {}


def glow_surface(radius, color, strength=1.0):
    color = tuple(color)
    key = (radius, color, round(strength, 2))
    surf = _GLOWS.get(key)
    if surf is not None:
        return surf
    surf = pygame.Surface((radius * 2, radius * 2))
    surf.fill((0, 0, 0))
    steps = max(6, radius // 2)
    for i in range(steps, 0, -1):
        t = i / steps
        f = (1.0 - t) ** 2 * strength
        c = (int(color[0] * f), int(color[1] * f), int(color[2] * f))
        pygame.draw.circle(surf, c, (radius, radius), int(radius * t))
    _GLOWS[key] = surf
    return surf


def blit_glow(surf, radius, color, center, strength=1.0):
    g = glow_surface(radius, color, strength)
    surf.blit(g, g.get_rect(center=center), special_flags=pygame.BLEND_ADD)


# --------------------------------------------------------------------------- #
# Sonido sintetizado (sin archivos externos)
# --------------------------------------------------------------------------- #

class Sfx:
    def __init__(self):
        self.ok = False
        self.muted = False
        self.music = None
        self.music_channel = None
        self.music_paused = False
        try:
            pygame.mixer.init(44100, -16, 1, 512)
        except pygame.error:
            return
        try:
            self.sounds = {
                "jump": self._tone(430, 780, 0.09, 0.16, 2.4),
                "land": self._tone(150, 90, 0.06, 0.10, 3.0),
                "death": self._tone(320, 60, 0.34, 0.20, 1.3, square=True),
                "win": self._arpeggio([523, 659, 784, 1046], 0.11, 0.16),
                "orb": self._tone(620, 1180, 0.14, 0.15, 2.0),
                "portal": self._tone(260, 900, 0.22, 0.14, 1.8),
                "flip": self._tone(180, 520, 0.08, 0.12, 2.6),
                "pad": self._tone(170, 1100, 0.24, 0.18, 1.7),
            }
            self.ok = True
        except Exception:
            self.ok = False
            return
        try:
            self.music = self._phonk_loop()
            self.start_music()
        except Exception:
            self.music = None

    @staticmethod
    def _sound(samples):
        """Convierte muestras mono int16 en un Sound (duplica si es estereo)."""
        init = pygame.mixer.get_init()
        channels = init[2] if init else 1
        data = array.array("h")
        if channels == 2:
            for value in samples:
                data.append(value)
                data.append(value)
        else:
            data.extend(samples)
        return pygame.mixer.Sound(buffer=data.tobytes())

    @classmethod
    def _tone(cls, f0, f1, dur, vol, decay, square=False):
        sr = 44100
        n = max(1, int(sr * dur))
        samples = []
        phase = 0.0
        for i in range(n):
            t = i / n
            f = f0 + (f1 - f0) * t
            phase += 2.0 * math.pi * f / sr
            s = math.sin(phase)
            if square:
                s = 1.0 if s >= 0 else -1.0
            env = (1.0 - t) ** decay
            samples.append(int(clamp(s * env * vol, -1.0, 1.0) * 32767))
        return cls._sound(samples)

    @classmethod
    def _arpeggio(cls, notes, dur, vol):
        sr = 44100
        n = int(sr * dur)
        samples = []
        for note in notes:
            for i in range(n):
                t = i / n
                s = math.sin(2.0 * math.pi * note * i / sr)
                env = (1.0 - t) ** 1.6
                samples.append(int(clamp(s * env * vol, -1.0, 1.0) * 32767))
        return cls._sound(samples)

    @classmethod
    def _phonk_loop(cls):
        """Sintetiza un bucle de phonk de 4 compases a 140 BPM (La menor).

        Sin archivos externos: bombo, caja, charles, 808 saturado y una
        melodia de campana.  El resultado se repite sin costuras porque las
        colas de las notas se mezclan de forma circular.
        """
        sr = 44100
        step = 60.0 / 140.0 / 4.0          # semicorchea
        n = int(round(sr * step * 16 * 4))
        buf = array.array("f", [0.0]) * n
        rnd = random.Random(140)
        tau = math.tau
        exp = math.exp
        sin = math.sin
        tanh = math.tanh

        def make(dur):
            return array.array("f", [0.0]) * int(sr * dur)

        def mix(wave, at_step, gain):
            off = int(round(at_step * step * sr)) % n
            ln = len(wave)
            cut = min(ln, n - off)
            for i in range(cut):
                buf[off + i] += wave[i] * gain
            for i in range(ln - cut):
                buf[i] += wave[cut + i] * gain

        # bombo: seno con caida de tono y un chasquido de ruido
        w = make(0.30)
        ph = 0.0
        for i in range(len(w)):
            t = i / sr
            ph += tau * (46.0 + 115.0 * exp(-t * 36.0)) / sr
            w[i] = (sin(ph) * exp(-t * 9.0)
                    + rnd.uniform(-1.0, 1.0) * exp(-t * 190.0) * 0.45)
        kick = w

        # caja: ruido agudo + cuerpo de 185 Hz
        w = make(0.20)
        prev = 0.0
        for i in range(len(w)):
            t = i / sr
            noise = rnd.uniform(-1.0, 1.0)
            hp = noise - prev * 0.85
            prev = noise
            w[i] = (hp * exp(-t * 16.0) * 0.52
                    + sin(tau * 185.0 * t) * exp(-t * 32.0) * 0.38)
        snare = w

        # charles: ruido con paso alto y caida muy rapida
        def hat(dur, decay, vol):
            w = make(dur)
            prev = 0.0
            for i in range(len(w)):
                t = i / sr
                noise = rnd.uniform(-1.0, 1.0)
                hp = noise - prev * 0.92
                prev = noise
                w[i] = hp * exp(-t * decay) * vol
            return w
        hat_closed = hat(0.055, 70.0, 0.9)
        hat_open = hat(0.16, 22.0, 0.7)

        # 808: seno grave con ataque de tono y saturacion suave
        def bass(root, dur=0.62):
            w = make(dur)
            ph = 0.0
            for i in range(len(w)):
                t = i / sr
                ph += tau * root * (1.0 + 1.35 * exp(-t * 26.0)) / sr
                env = min(1.0, t * 320.0) * exp(-t * 2.8)
                rem = dur - t
                if rem < 0.05:
                    env *= rem / 0.05
                w[i] = tanh(1.9 * sin(ph)) * 0.9 * env
            return w
        basses = [bass(root) for root in (55.0, 43.65, 65.41, 49.0)]

        # campana (cowbell): dos ondas cuadradas metalicas
        def cow(freq):
            dur = 0.19
            w = make(dur)
            p1 = p2 = 0.0
            for i in range(len(w)):
                t = i / sr
                p1 += tau * freq / sr
                p2 += tau * freq * 1.47 / sr
                s1 = 1.0 if sin(p1) >= 0.0 else -1.0
                s2 = 1.0 if sin(p2) >= 0.0 else -1.0
                env = min(1.0, t * 500.0) * exp(-t * 19.0)
                w[i] = (s1 * 0.6 + s2 * 0.4) * env * 0.55
            return w
        cowbell = {f: cow(f) for f in
                   (392.0, 440.0, 523.25, 587.33, 659.25, 783.99, 880.0)}

        # patrones (pasos de semicorchea dentro del compas)
        kicks = ([0, 6, 10], [0, 6, 10], [0, 6, 10], [0, 6, 10, 14])
        melody = (
            ((0, 440.0), (3, 523.25), (6, 440.0), (10, 659.25),
             (12, 587.33), (14, 523.25)),
            ((0, 440.0), (3, 523.25), (6, 659.25), (8, 587.33),
             (11, 523.25), (14, 440.0)),
            ((0, 392.0), (2, 440.0), (6, 523.25), (10, 659.25),
             (13, 587.33), (15, 523.25)),
            ((0, 440.0), (4, 523.25), (7, 659.25), (10, 880.0),
             (12, 783.99), (14, 659.25)),
        )
        for bar in range(4):
            base = bar * 16
            for s in kicks[bar]:
                mix(kick, base + s, 0.95)
            for s in (4, 12):
                mix(snare, base + s, 0.68)
            for s in range(0, 16, 2):
                mix(hat_closed, base + s, 0.36 if s % 4 == 0 else 0.24)
            if bar % 2 == 1:
                mix(hat_open, base + 14, 0.30)
                for s in (13.5, 14.5, 15.0, 15.5):
                    mix(hat_closed, base + s, 0.18)
            for s in (0, 7, 10):
                mix(basses[bar], base + s, 0.80)
            if bar == 3:
                mix(basses[0], base + 14, 0.55)
            for s, freq in melody[bar]:
                mix(cowbell[freq], base + s, 0.38)

        data = array.array("h")
        for value in buf:
            data.append(int(tanh(value * 0.85) * 32767))
        return cls._sound(data)

    def start_music(self):
        if not self.ok or self.music is None:
            return
        try:
            if pygame.mixer.get_num_channels() < 8:
                pygame.mixer.set_num_channels(12)
            # El canal 0 queda reservado para la musica: los efectos no lo roban.
            pygame.mixer.set_reserved(1)
            self.music_channel = pygame.mixer.Channel(0)
            self.music_channel.set_volume(0.34)
            self.music_channel.play(self.music, loops=-1)
        except Exception:
            self.music_channel = None

    def toggle_mute(self):
        self.muted = not self.muted
        if self.music_channel is not None:
            if self.muted:
                self.music_channel.pause()
            elif not self.music_paused:
                self.music_channel.unpause()
        return self.muted

    def pause_music(self):
        self.music_paused = True
        if self.music_channel is not None:
            self.music_channel.pause()

    def resume_music(self):
        self.music_paused = False
        if self.music_channel is not None and not self.muted:
            self.music_channel.unpause()

    def play(self, name):
        if self.ok and not self.muted:
            self.sounds[name].play()


# --------------------------------------------------------------------------- #
# Datos de colision
# --------------------------------------------------------------------------- #

MODE_CUBE, MODE_SHIP, MODE_BALL = 0, 1, 2
MODE_NAMES = ("CUBO", "NAVE", "BOLA")
DIMS = ((40.0, 40.0), (44.0, 28.0), (38.0, 38.0))
ORB_KINDS = {"orb_y": "y", "orb_p": "p", "orb_b": "b"}
ORB_COLORS = {"y": (255, 214, 64), "p": (255, 110, 200), "b": (90, 170, 255)}
ORB_R = 26.0
SHIP_ACCEL = 0.95
SHIP_FALL = 0.55
SHIP_MAX_V = 620.0
PORTAL_MODES = {"portal_ship": MODE_SHIP, "portal_ball": MODE_BALL,
                "portal_cube": MODE_CUBE}
PORTAL_COLORS = {"ship": (80, 190, 255), "ball": (255, 110, 200),
                 "cube": (90, 255, 160)}


class LevelData:
    def __init__(self, level):
        self.level = level
        self.finish_x = level.finish_x

        self.blocks = [pygame.Rect(int(o.x), int(o.y), int(o.w), int(o.h))
                       for o in level.blocks]

        self.hazards = []
        for o in level.spikes:
            if o.kind == "spike_down":
                self.hazards.append(pygame.Rect(int(o.x) + 10, int(o.y),
                                                int(o.w) - 20, int(o.h) - 13))
            else:
                self.hazards.append(pygame.Rect(int(o.x) + 10, int(o.y) + 13,
                                                int(o.w) - 20, int(o.h) - 13))
        self.hazards.sort(key=lambda r: r.x)
        self.hazard_starts = [r.x for r in self.hazards]

        # El circulo de dano es mas pequeno que el dibujo (perdon al jugador).
        self.saws = [(o.x + o.w / 2.0, o.y + o.h / 2.0 + 6.0, 27.0)
                     for o in level.saws]
        self.moving_saws = [
            (o.x + o.w / 2.0, o.y + o.h / 2.0 + 6.0, 27.0,
             o.meta["amp"], o.meta["omega"], o.meta["phase"])
            for o in level.moving_saws
        ]

        self.pads = [
            pygame.Rect(int(o.x) + 4, int(o.y) + int(o.h) - 14,
                        int(o.w) - 8, 14)
            for o in level.pads
        ]

        self.orbs = sorted(
            (o.x + o.w / 2.0, o.y + o.h / 2.0, ORB_KINDS[o.kind], k)
            for k, o in enumerate(level.orbs)
        )
        self.orb_starts = [o[0] for o in self.orbs]

        self.portals = sorted(
            (o.x + o.w / 2.0, PORTAL_MODES[o.kind]) for o in level.portals
        )

        self.pits = sorted((o.x, o.x + o.w) for o in level.pits)

    def over_pit(self, x, w=0.0):
        """True si la franja horizontal [x, x+w] pisa un vacio."""
        return any(x < b and x + w > a for a, b in self.pits)

    def pit_overlaps(self, x0, x1):
        return any(x0 < b and x1 > a for a, b in self.pits)

    def _near(self, items, starts, x, reach=220):
        i = bisect.bisect_left(starts, x - reach)
        out = []
        n = len(items)
        while i < n and starts[i] <= x + reach:
            out.append(items[i])
            i += 1
        return out

    def blocks_near(self, x):
        # Los techos son bloques muy largos: no basta con mirar su x inicial.
        return [r for r in self.blocks
                if r.right > x - 220 and r.left < x + 220]

    def hazards_near(self, x, reach=120):
        return self._near(self.hazards, self.hazard_starts, x, reach=reach)

    def saws_at(self, x, t, reach=200):
        """Sierras visibles cerca de ``x`` en el instante ``t``.

        Devuelve ``(cx, cy, radio, amplitud)``; la amplitud es 0 en las fijas.
        """
        out = [(cx, cy, rad, 0.0) for cx, cy, rad in self.saws
               if abs(cx - x) < reach]
        for cx, cy, rad, amp, omega, phase in self.moving_saws:
            if abs(cx - x) < reach:
                out.append((cx, cy + amp * math.sin(omega * t + phase),
                            rad, amp))
        return out

    def orbs_near(self, x, reach=90):
        return self._near(self.orbs, self.orb_starts, x, reach=reach)


# --------------------------------------------------------------------------- #
# Simulacion (independiente del dibujo, reutilizable por el bot de pruebas)
# --------------------------------------------------------------------------- #

class Sim:
    def __init__(self, data):
        self.data = data
        self.reset()

    def reset(self):
        self.mode = MODE_CUBE
        self.x = SPAWN_X
        self.hit_w, self.hit_h = DIMS[self.mode]
        self.y = GROUND_Y - self.hit_h
        self.vy = 0.0
        self.gdir = 1
        self.on_ground = True
        self.alive = True
        self.finished = False
        self.ang = 0.0
        self.events = []
        self.cause = None
        self.used_orbs = set()
        self.used_pads = set()
        self.next_portal = 0
        self.last_orb = "y"
        self.t = 0.0

    def die(self, cause):
        if self.alive:
            self.alive = False
            self.cause = cause
            self.events.append("death")

    def _set_mode(self, mode):
        if mode == self.mode:
            return
        bottom = self.y + self.hit_h
        self.mode = mode
        self.hit_w, self.hit_h = DIMS[mode]
        self.y = bottom - self.hit_h
        self.vy = 0.0
        self.gdir = 1
        self.on_ground = False
        self.ang = 0.0
        self.events.append("portal")

    def _use_orb(self, kind):
        self.last_orb = kind
        if kind == "b":
            self.gdir *= -1
            self.vy = -JUMP_V * 0.9 * self.gdir
        elif kind == "p":
            self.vy = -JUMP_V * 0.72 * self.gdir
        else:
            self.vy = -JUMP_V * self.gdir
        self.on_ground = False

    def _check_portals(self):
        portals = self.data.portals
        while self.next_portal < len(portals):
            px, mode = portals[self.next_portal]
            if self.x + self.hit_w * 0.5 >= px:
                self._set_mode(mode)
                self.next_portal += 1
            else:
                break

    def step(self, dt, held, pressed):
        if not self.alive or self.finished:
            return
        self.events.clear()
        self.t += dt
        was_ground = self.on_ground

        # --- entrada -------------------------------------------------------
        if self.mode == MODE_CUBE:
            if held and self.on_ground:
                self.vy = -JUMP_V * self.gdir
                self.on_ground = False
                self.events.append("jump")
        elif self.mode == MODE_BALL:
            if pressed:
                self.gdir *= -1
                self.on_ground = False
                self.vy = 0.0
                self.events.append("flip")

        # --- gravedad o propulsion ----------------------------------------
        if self.mode == MODE_SHIP:
            accel = -GRAVITY * SHIP_ACCEL if held else GRAVITY * SHIP_FALL
            self.vy = clamp(self.vy + accel * dt, -SHIP_MAX_V, SHIP_MAX_V)
        else:
            self.vy = clamp(self.vy + GRAVITY * self.gdir * dt, -1700.0, 1700.0)

        # --- avance horizontal --------------------------------------------
        h = self.hit_h
        prev_top = self.y
        prev_bottom = self.y + h
        self.x += SPEED * dt

        self._check_portals()
        w, h = self.hit_w, self.hit_h
        prev_top = self.y
        prev_bottom = self.y + h

        for r in self.data.blocks_near(self.x):
            if not hit(self.x, self.y, w, h, r):
                continue
            if self.mode == MODE_SHIP:
                self.die("wall")
                return
            if prev_bottom <= r.top + 8 or prev_top >= r.bottom - 8:
                continue
            self.die("wall")
            return

        # --- movimiento vertical y aterrizaje ------------------------------
        prev_top = self.y
        prev_bottom = self.y + h
        self.y += self.vy * dt
        self.on_ground = False

        for r in self.data.blocks_near(self.x):
            if not hit(self.x, self.y, w, h, r):
                continue
            if self.mode == MODE_SHIP:
                self.die("wall")
                return
            if self.vy >= 0 and prev_bottom <= r.top + 8:
                self.y = r.top - h
                self.vy = 0.0
                self.on_ground = True
            elif self.vy <= 0 and prev_top >= r.bottom - 8:
                self.y = r.bottom
                self.vy = 0.0
                self.on_ground = True
            else:
                self.die("wall")
                return

        # --- suelo y techo del mundo --------------------------------------
        over_pit = self.data.over_pit(self.x, w)
        if self.mode == MODE_SHIP:
            if self.y + h >= GROUND_Y and not over_pit:
                self.y = GROUND_Y - h
                self.vy = min(self.vy, 0.0)
                self.on_ground = True
            if self.y <= 0.0:
                self.y = 0.0
                self.vy = max(self.vy, 0.0)
        elif self.gdir > 0:
            if self.y + h >= GROUND_Y and not over_pit:
                self.y = GROUND_Y - h
                self.vy = 0.0
                self.on_ground = True
        else:
            if self.y <= 0.0:
                self.y = 0.0
                self.vy = 0.0
                self.on_ground = True

        # --- lava ----------------------------------------------------------
        if self.y + h >= LAVA_Y:
            self.die("lava")
            return

        if self.on_ground and not was_ground:
            self.events.append("land")

        # --- rampas de impulso ---------------------------------------------
        if self.mode == MODE_CUBE:
            for idx, pad in enumerate(self.data.pads):
                if idx in self.used_pads:
                    continue
                if (self.y + h >= pad.top - 3
                        and hit(self.x, self.y, w, h, pad)):
                    self.used_pads.add(idx)
                    self.vy = -PAD_V * self.gdir
                    self.on_ground = False
                    self.events.append("pad")
                    break

        # --- orbes ---------------------------------------------------------
        hx = self.x + HIT
        hy = self.y + HIT
        hw = w - 2.0 * HIT
        hh = h - 2.0 * HIT
        # Los orbes se activan manteniendo pulsado (como en Geometry Dash),
        # no hace falta un clic nuevo.
        if held:
            for ox, oy, kind, idx in self.data.orbs_near(self.x):
                if idx in self.used_orbs:
                    continue
                if circle_hits_rect(ox, oy, ORB_R, hx, hy, hw, hh):
                    self.used_orbs.add(idx)
                    self._use_orb(kind)
                    self.events.append("orb")
                    break

        # --- pinchos y sierras ---------------------------------------------
        for r in self.data.hazards_near(self.x):
            if hit(hx, hy, hw, hh, r):
                self.die("spike")
                return
        for cx, cy, radius, _amp in self.data.saws_at(self.x, self.t):
            if circle_hits_rect(cx, cy, radius, hx, hy, hw, hh):
                self.die("saw")
                return

        # --- rotacion ------------------------------------------------------
        if self.mode == MODE_SHIP:
            self.ang = clamp(self.vy * 0.055, -34.0, 34.0)
        elif self.mode == MODE_BALL:
            self.ang = (self.ang + SPEED * dt / 19.0 * 57.2958 * self.gdir) % 360.0
        elif self.on_ground:
            self.ang = round(self.ang / 90.0) * 90.0
        else:
            self.ang = (self.ang + JUMP_ROT * dt * self.gdir) % 360.0

        # --- meta ----------------------------------------------------------
        if self.x >= self.data.finish_x:
            self.finished = True
            self.events.append("finish")

    def progress(self):
        span = max(1.0, self.data.finish_x - SPAWN_X)
        return clamp((self.x - SPAWN_X) / span, 0.0, 1.0)


# --------------------------------------------------------------------------- #
# Particulas
# --------------------------------------------------------------------------- #

class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "color", "size",
                 "gravity", "add")

    def __init__(self, x, y, vx, vy, life, color, size, gravity=0.0, add=True):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.life = life
        self.max_life = life
        self.color = color
        self.size = size
        self.gravity = gravity
        self.add = add


# --------------------------------------------------------------------------- #
# Guardado de records
# --------------------------------------------------------------------------- #

def save_path():
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    folder = os.path.join(base, "neon-dash")
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        folder = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(folder, "save.json")


def load_records():
    try:
        with open(save_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def store_records(records):
    try:
        with open(save_path(), "w", encoding="utf-8") as fh:
            json.dump(records, fh, indent=2)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Juego
# --------------------------------------------------------------------------- #

class Game:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Neon Dash")
        self.win = pygame.display.set_mode((W, H), pygame.RESIZABLE)
        self.canvas = pygame.Surface((W, H)).convert()
        self.clock = pygame.time.Clock()

        self.font_title = load_font(104, bold=True)
        self.font_big = load_font(56, bold=True)
        self.font_card = load_font(23, bold=True)
        self.font_mid = load_font(26, bold=True)
        self.font_small = load_font(19)
        self.font_tiny = load_font(15)

        self.sfx = Sfx()
        self.records = load_records()

        self.state = MENU
        self.sel = 0
        self.t = 0.0
        self.acc = 0.0
        self.shake = 0.0
        self.dead_t = 0.0
        self.win_t = 0.0
        self.flash = 0.0
        self.saw_angle = 0.0
        self.trail_t = 0.0
        self.particles = []
        self.cam = 0.0
        self.jump_held = False
        self.attempts = 1
        self.practice = False
        self.checkpoints = []

        self.scale = 1.0
        self.off = (0, 0)
        self.fullscreen = False
        self.card_rects = []

        self.load_level(0)

        self.stars = [(random.random() * W, random.random() * (GROUND_Y - 120),
                       random.choice((1, 1, 1, 2)), random.random() * 1.7,
                       random.uniform(0.08, 0.3)) for _ in range(90)]
        self.hills = [(random.randint(70, 210), random.randint(140, 300))
                      for _ in range(10)]

    # -- niveles ------------------------------------------------------------
    def load_level(self, index):
        self.sel = index % len(LEVELS)
        self.level = LEVELS[self.sel]
        self.theme = self.level.theme
        self.data = LevelData(self.level)
        self.sim = Sim(self.data)
        self.checkpoints.clear()
        self.cam = 0.0
        self.acc = 0.0
        self.attempts = 1
        self.particles.clear()
        self.build_sprites()

    def build_sprites(self):
        th = self.theme
        self.bg = pygame.Surface((1, H))
        top, bottom = th["sky_top"], th["sky_bottom"]
        for y in range(H):
            f = (y / (H - 1)) ** 0.85
            self.bg.set_at((0, y), (
                int(top[0] + (bottom[0] - top[0]) * f),
                int(top[1] + (bottom[1] - top[1]) * f),
                int(top[2] + (bottom[2] - top[2]) * f),
            ))
        self.bg = pygame.transform.smoothscale(self.bg, (W, H)).convert()

        # pincho
        sp = pygame.Surface((TILE, TILE), pygame.SRCALPHA)
        pts = [(1, TILE - 1), (TILE / 2, 2), (TILE - 1, TILE - 1)]
        pygame.draw.polygon(sp, th["spike"], pts)
        pygame.draw.polygon(sp, (255, 255, 255), pts, 2)
        pygame.draw.polygon(sp, (255, 255, 255, 70),
                            [(TILE * 0.5, 8), (TILE * 0.72, TILE - 4), (TILE * 0.28, TILE - 4)])
        self.img_spike = sp
        self.img_spike_down = pygame.transform.flip(sp, False, True)

        # bloque
        bl = pygame.Surface((TILE, TILE), pygame.SRCALPHA)
        pygame.draw.rect(bl, (12, 10, 26, 240), (0, 0, TILE, TILE), border_radius=6)
        pygame.draw.rect(bl, th["block"], (4, 4, TILE - 8, TILE - 8), border_radius=4)
        pygame.draw.rect(bl, th["block_edge"], (1, 1, TILE - 2, TILE - 2), 2, border_radius=6)
        pygame.draw.line(bl, (255, 255, 255, 45), (6, 6), (TILE - 8, 6), 2)
        self.img_block = bl

        # sierra
        r = 40
        d = r * 2 + 6
        c = d // 2
        sw = pygame.Surface((d, d), pygame.SRCALPHA)
        teeth = []
        for i in range(20):
            a = i * math.pi / 10
            rad = r if i % 2 == 0 else r - 9
            teeth.append((c + math.cos(a) * rad, c + math.sin(a) * rad))
        pygame.draw.polygon(sw, th["spike"], teeth)
        pygame.draw.circle(sw, (16, 12, 30), (c, c), r - 15)
        pygame.draw.circle(sw, th["spike"], (c, c), r - 15, 3)
        pygame.draw.circle(sw, (16, 12, 30), (c, c), 7)
        pygame.draw.circle(sw, (220, 220, 240), (c, c), 7, 1)
        self.img_saw = sw

        # rampa de impulso
        pd = pygame.Surface((TILE, TILE), pygame.SRCALPHA)
        pygame.draw.polygon(pd, th["accent2"],
                            [(3, 35), (20, 18), (37, 35), (37, 39), (3, 39)])
        pygame.draw.polygon(pd, (255, 255, 255), [(3, 35), (20, 18), (37, 35)], 2)
        pygame.draw.rect(pd, th["accent"], (3, 37, 34, 3), border_radius=2)
        pygame.draw.polygon(pd, (255, 255, 255),
                            [(20, 3), (31, 14), (24, 14), (24, 24),
                             (16, 24), (16, 14), (9, 14)])
        self.img_pad = pd

        # cubo del jugador
        s = 52
        cube = pygame.Surface((s, s), pygame.SRCALPHA)
        body = pygame.Rect(4, 4, s - 8, s - 8)
        pygame.draw.rect(cube, th["player"], body, border_radius=10)
        light = tuple(min(255, c + 70) for c in th["player"])
        pygame.draw.rect(cube, light, body.inflate(-14, -14), border_radius=5)
        pygame.draw.rect(cube, (255, 255, 255), (16, 13, 12, 5), border_radius=2)
        pygame.draw.rect(cube, (255, 255, 255), body, 4, border_radius=10)
        self.img_cube = cube
        self.img_cube_small = pygame.transform.smoothscale(cube, (26, 26))

        # orbes de salto
        self.img_orb = {}
        for kind, col in ORB_COLORS.items():
            d = 58
            mid = d // 2
            orb = pygame.Surface((d, d), pygame.SRCALPHA)
            pygame.draw.circle(orb, (12, 12, 24, 170), (mid, mid), 24)
            pygame.draw.circle(orb, col, (mid, mid), 24, 3)
            pygame.draw.circle(orb, col, (mid, mid), 16, 2)
            pygame.draw.circle(orb, (255, 255, 255), (mid, mid), 8)
            pygame.draw.circle(orb, (255, 255, 255), (mid - 8, mid - 8), 4)
            self.img_orb[kind] = orb

        # portales de cambio de modo
        self.img_portal = {}
        for mode, col in PORTAL_COLORS.items():
            ph = TILE * 3
            pt = pygame.Surface((TILE, ph), pygame.SRCALPHA)
            pygame.draw.rect(pt, (*col, 46), (3, 3, TILE - 6, ph - 6),
                             border_radius=15)
            pygame.draw.rect(pt, col, (3, 3, TILE - 6, ph - 6), 3,
                             border_radius=15)
            pygame.draw.rect(pt, (*col, 150), (11, 11, TILE - 22, ph - 22), 1,
                             border_radius=10)
            mid = ph // 2
            if mode == "ship":
                pygame.draw.polygon(pt, col, [(12, mid + 9), (28, mid),
                                              (12, mid - 9)])
            elif mode == "ball":
                pygame.draw.circle(pt, col, (20, mid), 9, 2)
                pygame.draw.circle(pt, col, (20, mid), 3)
            else:
                pygame.draw.rect(pt, col, (11, mid - 9, 18, 18), 2,
                                 border_radius=3)
            self.img_portal[mode] = pt

        # nave y bola del jugador
        ship = pygame.Surface((60, 42), pygame.SRCALPHA)
        hull = [(4, 27), (32, 8), (56, 21), (32, 34)]
        pygame.draw.polygon(ship, th["player"], hull)
        pygame.draw.polygon(ship, (255, 255, 255), hull, 3)
        light = tuple(min(255, c + 70) for c in th["player"])
        pygame.draw.circle(ship, (14, 14, 30), (31, 21), 8)
        pygame.draw.circle(ship, light, (31, 21), 5)
        self.img_ship = ship

        ball = pygame.Surface((52, 52), pygame.SRCALPHA)
        pygame.draw.circle(ball, th["player"], (26, 26), 21)
        pygame.draw.circle(ball, (14, 14, 30), (26, 26), 21, 3)
        pygame.draw.circle(ball, (255, 255, 255), (26, 26), 21, 2)
        pygame.draw.rect(ball, (14, 14, 30), (20, 7, 12, 38), 3, border_radius=3)
        pygame.draw.rect(ball, (14, 14, 30), (7, 20, 38, 12), 3, border_radius=3)
        pygame.draw.circle(ball, (255, 255, 255), (26, 26), 5)
        self.img_ball = ball

        self.orb_index = {id(o): k for k, o in enumerate(self.level.orbs)}

    # -- ciclo de vida ------------------------------------------------------
    def start(self):
        self.checkpoints.clear()
        self.sim.reset()
        self.cam = 0.0
        self.acc = 0.0
        self.attempts = 1
        self.particles.clear()
        self.jump_held = False
        self.state = PLAY
        self.flash = 0.0
        self.sfx.resume_music()

    def restart(self):
        self.checkpoints.clear()
        self.sim.reset()
        self.cam = 0.0
        self.acc = 0.0
        self.attempts = 1
        self.particles.clear()
        self.jump_held = False
        self.state = PLAY
        self.sfx.resume_music()

    def respawn(self):
        self.sim.reset()
        if self.practice and self.checkpoints:
            self.sim.__dict__.update(copy.deepcopy(self.checkpoints[-1]))
        self.cam = max(0.0, self.sim.x - W * 0.30)
        self.acc = 0.0
        self.attempts += 1
        self.particles.clear()
        self.jump_held = False
        self.state = PLAY
        self.sfx.resume_music()

    def place_checkpoint(self):
        if not self.practice or self.state != PLAY or not self.sim.alive:
            return
        # Guardar el reloj y los consumibles conserva sierras, portales y orbes.
        snapshot = copy.deepcopy({k: v for k, v in vars(self.sim).items()
                                  if k != "data"})
        snapshot["events"] = []
        self.checkpoints.append(snapshot)
        # Limite de memoria; X permite volver a un punto anterior.
        self.checkpoints = self.checkpoints[-50:]

    def record(self):
        if self.practice:
            return
        key = self.level.name
        entry = self.records.get(key, {"best": 0, "done": False})
        pct = int(round(self.sim.progress() * 100))
        if pct > entry.get("best", 0):
            entry["best"] = pct
        if self.sim.finished:
            entry["done"] = True
            entry["best"] = 100
        self.records[key] = entry
        store_records(self.records)

    # -- eventos ------------------------------------------------------------
    def handle_event(self, ev):
        if ev.type == pygame.QUIT:
            return False
        if ev.type == pygame.VIDEORESIZE and not self.fullscreen:
            self.win = pygame.display.set_mode((max(480, ev.w), max(320, ev.h)),
                                               pygame.RESIZABLE)
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and self.state == MENU:
            mx, my = self.to_canvas(ev.pos)
            for i, rect in self.card_rects:
                if rect.collidepoint(mx, my):
                    if i == self.sel:
                        self.start()
                    else:
                        self.load_level(i)
                    break
            return True
        if ev.type != pygame.KEYDOWN:
            return True

        key = ev.key
        if key == pygame.K_F11:
            self.toggle_fullscreen()
            return True
        if key == pygame.K_m:
            self.sfx.toggle_mute()
            return True

        if key == pygame.K_p and self.state in (MENU, PLAY, PAUSE):
            self.practice = not self.practice
            self.checkpoints.clear()
            if self.state != MENU:
                self.restart()
            return True
        if key == pygame.K_z and self.state == PLAY:
            self.place_checkpoint()
            return True
        if key == pygame.K_x and self.practice and self.state in (PLAY, PAUSE, DEAD):
            if self.checkpoints:
                self.checkpoints.pop()
            return True

        if self.state == MENU:
            if key in (pygame.K_ESCAPE, pygame.K_q):
                return False
            if key in (pygame.K_LEFT, pygame.K_a, pygame.K_UP, pygame.K_w):
                self.load_level(self.sel - 1)
            elif key in (pygame.K_RIGHT, pygame.K_d, pygame.K_DOWN, pygame.K_s):
                self.load_level(self.sel + 1)
            elif key in (pygame.K_SPACE, pygame.K_RETURN, pygame.K_KP_ENTER):
                self.start()
        elif self.state == PLAY:
            if key == pygame.K_ESCAPE:
                self.state = PAUSE
                self.sfx.pause_music()
            elif key == pygame.K_r:
                self.restart()
        elif self.state == PAUSE:
            if key == pygame.K_ESCAPE:
                self.state = PLAY
                self.sfx.resume_music()
            elif key == pygame.K_r:
                self.restart()
            elif key == pygame.K_q:
                self.state = MENU
                self.sfx.resume_music()
                self.load_level(self.sel)
        elif self.state == DEAD:
            if key == pygame.K_ESCAPE:
                self.state = MENU
                self.load_level(self.sel)
            elif key == pygame.K_r:
                self.respawn()
        elif self.state == WIN:
            if key in (pygame.K_SPACE, pygame.K_RETURN, pygame.K_ESCAPE) and self.win_t > 0.5:
                self.state = MENU
                self.load_level(self.sel)
        return True

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        if self.fullscreen:
            self.win = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            self.win = pygame.display.set_mode((W, H), pygame.RESIZABLE)

    # -- actualizacion ------------------------------------------------------
    def update(self, dt):
        self.t += dt
        self.saw_angle = (self.saw_angle - 200.0 * dt) % 360.0
        self.shake = max(0.0, self.shake - dt * 30.0)
        self.flash = max(0.0, self.flash - dt * 3.2)

        # El borde de pulsacion se calcula una vez por fotograma: la bola
        # necesita un toque nuevo para girar la gravedad.
        held = self.read_jump()
        pressed = held and not self.jump_held
        self.jump_held = held

        if self.state == MENU:
            self.cam = (self.cam + 55.0 * dt) % max(1.0, self.level.length - W)
            self.update_particles(dt)
            return

        if self.state == PLAY:
            self.acc += dt
            if self.acc > 0.2:
                self.acc = 0.2
            first = pressed
            while self.acc >= STEP:
                self.sim.step(STEP, held, first)
                first = False
                for ev_name in self.sim.events:
                    self.on_event(ev_name)
                self.acc -= STEP
                if self.state != PLAY:
                    break
            if self.state == PLAY:
                target = max(0.0, self.sim.x - W * 0.30)
                self.cam += (target - self.cam) * min(1.0, dt * 9.0)
                self.emit_trail(dt)
            self.update_particles(dt)
            return

        if self.state == DEAD:
            self.dead_t += dt
            self.update_particles(dt)
            if self.dead_t > 0.55:
                self.respawn()
            return

        if self.state == WIN:
            self.win_t += dt
            self.cam += (max(0.0, self.sim.x - W * 0.30) - self.cam) * min(1.0, dt * 9.0)
            self.update_particles(dt)
            return

        # PAUSE
        self.update_particles(dt)

    def read_jump(self):
        keys = pygame.key.get_pressed()
        return bool(keys[pygame.K_SPACE] or keys[pygame.K_UP] or keys[pygame.K_w]
                    or pygame.mouse.get_pressed()[0])

    def on_event(self, name):
        sim = self.sim
        hw, hh = sim.hit_w, sim.hit_h
        cx, cy = sim.x + hw / 2, sim.y + hh / 2
        if name == "jump":
            self.sfx.play("jump")
            self.burst(sim.x + hw / 2, sim.y + hh, 4, self.theme["player"],
                       spread=90, life=0.28, size=2.5)
        elif name == "land":
            self.sfx.play("land")
            self.burst(sim.x + hw / 2, sim.y + hh, 7, self.theme["accent"],
                       spread=130, life=0.35, size=2.0, upward=False)
        elif name == "flip":
            self.sfx.play("flip")
            self.burst(cx, cy, 10, self.theme["accent"], 150, 0.32, 2.4,
                       upward=sim.gdir > 0)
        elif name == "pad":
            self.sfx.play("pad")
            self.burst(cx, sim.y + hh, 18, self.theme["accent2"],
                       270, 0.5, 3.4)
        elif name == "orb":
            self.sfx.play("orb")
            col = ORB_COLORS.get(sim.last_orb, self.theme["accent"])
            self.burst(cx, cy, 16, col, 210, 0.45, 3.0)
        elif name == "portal":
            self.sfx.play("portal")
            col = PORTAL_COLORS.get(
                {MODE_SHIP: "ship", MODE_BALL: "ball"}.get(sim.mode, "cube"),
                self.theme["accent"])
            self.flash = max(self.flash, 0.45)
            self.burst(cx, cy, 26, col, 280, 0.6, 3.2)
        elif name == "death":
            self.sfx.play("death")
            self.state = DEAD
            self.dead_t = 0.0
            self.shake = 16.0
            self.flash = 1.0
            self.explode()
            self.record()
        elif name == "finish":
            self.sfx.play("win")
            self.state = WIN
            self.win_t = 0.0
            self.shake = 8.0
            self.record()
            for _ in range(90):
                self.particles.append(Particle(
                    random.uniform(self.sim.x - 80, self.sim.x + 200),
                    random.uniform(GROUND_Y - 320, GROUND_Y - 40),
                    random.uniform(-140, 140), random.uniform(-260, -40),
                    random.uniform(1.0, 2.4),
                    random.choice((self.theme["accent"], self.theme["accent2"],
                                   (255, 255, 255))),
                    random.uniform(2, 5), gravity=420.0))

    def burst(self, x, y, n, color, spread, life, size, upward=True):
        for _ in range(n):
            ang = random.uniform(-math.pi, 0) if upward else random.uniform(0, math.pi)
            sp = random.uniform(40, spread)
            self.particles.append(Particle(
                x + random.uniform(-8, 8), y + random.uniform(-4, 4),
                math.cos(ang) * sp, math.sin(ang) * sp,
                life * random.uniform(0.6, 1.3), color,
                size * random.uniform(0.6, 1.4), gravity=180.0))

    def explode(self):
        cx = self.sim.x + self.sim.hit_w / 2
        cy = self.sim.y + self.sim.hit_h / 2
        colors = (self.theme["player"], self.theme["accent"], (255, 255, 255))
        for _ in range(70):
            ang = random.uniform(0, math.tau)
            sp = random.uniform(60, 620)
            self.particles.append(Particle(
                cx, cy, math.cos(ang) * sp, math.sin(ang) * sp,
                random.uniform(0.35, 1.0), random.choice(colors),
                random.uniform(2, 6), gravity=560.0))

    def emit_trail(self, dt):
        self.trail_t += dt
        while self.trail_t > 0.022:
            self.trail_t -= 0.022
            self.particles.append(Particle(
                self.sim.x + random.uniform(-4, 10),
                self.sim.y + random.uniform(4, max(5.0, self.sim.hit_h - 4)),
                random.uniform(-170, -60), random.uniform(-20, 20),
                random.uniform(0.18, 0.42),
                random.choice((self.theme["player"], self.theme["accent"])),
                random.uniform(1.5, 3.2), gravity=0.0))

    def update_particles(self, dt):
        alive = []
        for p in self.particles:
            p.life -= dt
            if p.life <= 0:
                continue
            p.vy += p.gravity * dt
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.vx *= 1.0 - 1.4 * dt
            alive.append(p)
        self.particles = alive[-500:]

    # -- dibujo -------------------------------------------------------------
    def present(self):
        cw, ch = self.win.get_size()
        scale = min(cw / W, ch / H)
        dw, dh = int(W * scale), int(H * scale)
        self.scale = scale
        self.off = ((cw - dw) // 2, (ch - dh) // 2)
        self.win.fill((0, 0, 0))
        if (dw, dh) == (W, H):
            self.win.blit(self.canvas, self.off)
        else:
            self.win.blit(pygame.transform.smoothscale(self.canvas, (dw, dh)), self.off)
        pygame.display.flip()

    def to_canvas(self, pos):
        return ((pos[0] - self.off[0]) / self.scale,
                (pos[1] - self.off[1]) / self.scale)

    def draw_theme_decor(self):
        """Decoracion de fondo propia de cada nivel."""
        c = self.canvas
        th = self.theme
        style = th.get("style", "sun")

        def blend(a, b, t):
            return (int(a[0] + (b[0] - a[0]) * t),
                    int(a[1] + (b[1] - a[1]) * t),
                    int(a[2] + (b[2] - a[2]) * t))

        if style == "sun":
            # sol sintwave con bandas y rejilla en perspectiva
            cx, cy = int(W * 0.76), GROUND_Y - 6
            for i in range(28):
                f = i / 27.0
                pygame.draw.circle(c, blend((255, 232, 120), (255, 40, 130), f),
                                   (cx, cy), 138 - i * 5)
            for i in range(7):
                yy = cy - 34 - i * 14
                pygame.draw.rect(c, th["sky_bottom"], (cx - 150, yy, 300, 2 + i))
            col = blend(th["stripe"], th["accent"], 0.35)
            for i in range(6):
                yy = GROUND_Y + 16 + i * i * 4
                if yy < H:
                    pygame.draw.line(c, col, (0, yy), (W, yy), 1)
        elif style == "rings":
            # anillos concentricos flotando
            for i, (bx, by, br, spd) in enumerate((
                    (W * 0.18, 200, 150, 9),
                    (W * 0.70, 320, 96, -13),
                    (W * 0.46, 118, 62, 17))):
                x = bx + math.sin(self.t * 0.20 + i * 1.4) * 26
                y = by + math.cos(self.t * 0.16 + i * 2.1) * 15
                for k in range(3):
                    r = br - k * 24 + math.sin(self.t * spd * 0.06 + k) * 4
                    if r > 6:
                        col = blend(th["sky_bottom"], th["accent2"],
                                    0.42 - k * 0.10)
                        pygame.draw.circle(c, col, (int(x), int(y)),
                                           int(r), 2 if k == 0 else 1)
        elif style == "orbit":
            # planeta anillado y una luna girando
            px, py = int(W * 0.78), 196
            for rr, col in ((190, th["far"]), (162, th["near"])):
                pygame.draw.ellipse(c, col, (px - rr, py - rr * 0.20,
                                             rr * 2, rr * 0.40), 2)
            for i in range(22):
                f = i / 21.0
                pygame.draw.circle(c, blend(th["accent2"], th["sky_top"],
                                            f * 0.85), (px, py), 98 - i * 4)
            pygame.draw.ellipse(c, blend(th["accent"], th["sky_top"], 0.25),
                                (px - 156, py - 28, 312, 56), 3)
            ang = self.t * 0.55
            mx = px + math.cos(ang) * 156
            my = py + math.sin(ang) * 30
            blit_glow(c, 26, th["accent"], (mx, my), 0.5)
            pygame.draw.circle(c, th["accent"], (int(mx), int(my)), 6)
        elif style == "embers":
            # ascuas que suben desde el suelo
            for i in range(52):
                x = (i * 173.0 + math.sin(self.t * 0.8 + i) * 34) % W
                y = GROUND_Y - ((self.t * 42.0 + i * 59.0) % 470.0)
                a = 0.30 + 0.70 * abs(math.sin(self.t * 3.0 + i * 0.9))
                col = (int(255 * a), int((90 + (i % 4) * 34) * a),
                       int(30 * a))
                pygame.draw.circle(c, col, (int(x), int(y)), 1 + i % 3)

    def draw_background(self):
        c = self.canvas
        c.blit(self.bg, (0, 0))
        th = self.theme
        self.draw_theme_decor()

        # estrellas
        for sx, sy, size, phase, layer in self.stars:
            x = (sx - self.cam * layer) % (W + 40) - 20
            a = 0.35 + 0.65 * abs(math.sin(self.t * 1.6 + phase))
            col = (int(120 * a + 40), int(150 * a + 40), int(220 * a + 30))
            pygame.draw.circle(c, col, (int(x), int(sy)), size)

        # colinas / triangulos de fondo
        for depth, (factor, color, base) in enumerate((
                (0.18, th["far"], 0.0), (0.34, th["near"], 60.0))):
            off = self.cam * factor
            for i in range(-1, W // 300 + 2):
                idx = (i + int(off // 300)) % len(self.hills)
                h, w = self.hills[idx]
                x = i * 300 - (off % 300)
                pygame.draw.polygon(c, color, [
                    (x, GROUND_Y + base),
                    (x + w / 2, GROUND_Y + base - h),
                    (x + w, GROUND_Y + base),
                ])

        # suelo
        pygame.draw.rect(c, th["ground"], (0, GROUND_Y, W, H - GROUND_Y))
        step = 80
        off = int(self.cam) % step
        for x in range(-off - step, W + step, step):
            pygame.draw.line(c, th["stripe"], (x, GROUND_Y + 6), (x, H), 2)
        pygame.draw.line(c, th["stripe"], (0, GROUND_Y + 44), (W, GROUND_Y + 44), 1)

        for i in range(7):
            f = (1.0 - i / 6.0) ** 2
            col = (int(th["accent"][0] * f * 0.55),
                   int(th["accent"][1] * f * 0.55),
                   int(th["accent"][2] * f * 0.55))
            pygame.draw.line(c, col, (0, GROUND_Y + i), (W, GROUND_Y + i), 1)

        self.draw_lava()

    def draw_lava(self):
        """Dibuja los vacios y la lava que hay en el fondo."""
        if not self.data.pits:
            return
        c = self.canvas
        for a, b in self.data.pits:
            x = a - self.cam
            w = b - a
            if x > W + 20 or x + w < -20:
                continue
            xi, wi = int(x), int(w)
            # camara del vacio
            pygame.draw.rect(c, (7, 3, 10), (xi, GROUND_Y, wi, H - GROUND_Y))
            # paredes laterales
            wall = (max(28, self.theme["ground"][0] + 12),
                    max(12, self.theme["ground"][1] + 8),
                    max(18, self.theme["ground"][2] + 10))
            pygame.draw.rect(c, wall, (xi, GROUND_Y, 6, H - GROUND_Y))
            pygame.draw.rect(c, wall, (xi + wi - 6, GROUND_Y, 6, H - GROUND_Y))
            pygame.draw.line(c, self.theme["block_edge"], (xi, GROUND_Y),
                             (xi, H), 1)
            pygame.draw.line(c, self.theme["block_edge"], (xi + wi - 1, GROUND_Y),
                             (xi + wi - 1, H), 1)
            # lava con gradiente
            for i in range(8):
                f = i / 7.0
                pygame.draw.rect(c, (255, int(90 + 100 * f), int(18 + 26 * f)),
                                 (xi + 5, LAVA_Y + i * 5, max(0, wi - 10), 5))
            blit_glow(c, min(120, wi // 2 + 34), (255, 90, 20),
                      (xi + wi / 2, LAVA_Y + 2), 0.55)
            # superficie ondulada
            prev = None
            for xx in range(max(xi, -16), min(xi + wi, W + 16), 8):
                yy = int(LAVA_Y + 2 + 3 * math.sin(
                    (xx + self.cam) * 0.055 + self.t * 3.6)
                    + 2 * math.sin((xx + self.cam) * 0.13 - self.t * 2.2))
                if prev is not None:
                    pygame.draw.line(c, (255, 220, 120), prev, (xx, yy), 2)
                prev = (xx, yy)
            # burbujas
            for i in range(max(2, wi // 70)):
                bt = (self.t * 0.8 + i * 0.31) % 1.0
                bx = xi + 14 + (i * 97 + int(self.t * 26)) % max(1, wi - 28)
                by = int(LAVA_Y - 4 - 16 * bt)
                pygame.draw.circle(c, (255, int(180 - 90 * bt), 50),
                                   (bx, by), 2 + i % 2)

    def draw_level(self, cam):
        c = self.canvas
        th = self.theme
        for o in self.level.objs:
            sx = o.x - cam
            if sx > W + 90 or sx + o.w < -90:
                continue
            if o.kind == "spike":
                c.blit(self.img_spike, (int(sx), int(o.y)))
            elif o.kind == "spike_down":
                c.blit(self.img_spike_down, (int(sx), int(o.y)))
            elif o.kind == "block":
                for gy in range(0, int(o.h), TILE):
                    for gx in range(0, int(o.w), TILE):
                        c.blit(self.img_block, (int(sx) + gx, int(o.y) + gy))
            elif o.kind == "saw" or o.kind == "saw_move":
                cx = sx + o.w / 2
                if o.kind == "saw_move":
                    amp = o.meta["amp"]
                    cy = o.y + o.h / 2 + amp * math.sin(
                        o.meta["omega"] * self.sim.t + o.meta["phase"])
                    pygame.draw.line(c, (*th["block_edge"], 45),
                                     (cx, o.y + o.h / 2 - amp - 18),
                                     (cx, o.y + o.h / 2 + amp + 18), 2)
                else:
                    cy = o.y + o.h / 2
                blit_glow(c, 70, th["spike"], (cx, cy), 0.55)
                img = pygame.transform.rotozoom(self.img_saw, self.saw_angle, 1.0)
                c.blit(img, img.get_rect(center=(cx, cy)))
            elif o.kind == "pad":
                cx = sx + o.w / 2
                pulse = 0.5 + 0.5 * abs(math.sin(self.t * 5.0 + o.x * 0.01))
                blit_glow(c, 40, th["accent2"], (cx, o.y + 30), 0.45 + 0.35 * pulse)
                c.blit(self.img_pad, (int(sx), int(o.y)))
            elif o.kind.startswith("orb_"):
                kind = ORB_KINDS[o.kind]
                col = ORB_COLORS[kind]
                cx = sx + o.w / 2
                cy = o.y + o.h / 2 + math.sin(self.t * 3.0 + o.x * 0.02) * 4.0
                used = self.orb_index.get(id(o)) in self.sim.used_orbs
                img = self.img_orb[kind]
                if used:
                    img = img.copy()
                    img.set_alpha(70)
                else:
                    blit_glow(c, 46, col, (cx, cy), 0.55)
                c.blit(img, img.get_rect(center=(cx, cy)))
            elif o.kind.startswith("portal_"):
                mode = o.kind.split("_", 1)[1]
                col = PORTAL_COLORS[mode]
                cx = sx + o.w / 2
                cy = o.y + o.h / 2
                pulse = 0.55 + 0.45 * abs(math.sin(self.t * 2.6 + o.x * 0.01))
                if self.sim.x < o.x + o.w:
                    blit_glow(c, 92, col, (cx, cy), 0.45 * pulse)
                c.blit(self.img_portal[mode], (int(sx), int(o.y)))

        # linea de meta
        fx = self.level.finish_x - cam
        if -120 < fx < W + 120:
            alto = 430
            blit_glow(c, 130, th["accent"], (fx + 10, GROUND_Y - 170), 0.75)
            for i in range(0, alto, 20):
                y = GROUND_Y - alto + i
                claro = (i // 20) % 2 == 0
                c.fill((245, 245, 255) if claro else (58, 58, 92), (fx - 12, y, 11, 20))
                c.fill((58, 58, 92) if claro else (245, 245, 255), (fx, y, 11, 20))
            pygame.draw.rect(c, th["accent"], (fx - 14, GROUND_Y - alto, 27, 4))
            pygame.draw.rect(c, th["accent"], (fx - 14, GROUND_Y - 4, 27, 4))

    def draw_player(self, cam, ox, oy):
        sim = self.sim
        if self.state == DEAD:
            return

        w, h = sim.hit_w, sim.hit_h
        cx = sim.x - cam + w / 2 + ox
        cy = sim.y + h / 2 + oy
        th = self.theme

        blit_glow(self.canvas, 72, th["player"], (cx + 6, cy), 0.36)

        if sim.mode == MODE_SHIP:
            if self.jump_held and self.state == PLAY:
                fx = cx - 26
                flick = random.uniform(0, 9)
                pygame.draw.polygon(self.canvas, (255, 200, 90),
                                    [(fx, cy - 7), (fx - 15 - flick, cy),
                                     (fx, cy + 7)])
                pygame.draw.polygon(self.canvas, (255, 255, 220),
                                    [(fx, cy - 3), (fx - 8 - flick * 0.5, cy),
                                     (fx, cy + 3)])
            img = pygame.transform.rotozoom(self.img_ship, -sim.ang, 1.0)
        elif sim.mode == MODE_BALL:
            img = pygame.transform.rotozoom(self.img_ball, -sim.ang, 1.0)
        else:
            img = pygame.transform.rotozoom(self.img_cube, -sim.ang, 1.0)
        self.canvas.blit(img, img.get_rect(center=(cx, cy)))

    def draw_particles(self, cam, ox, oy):
        c = self.canvas
        for p in self.particles:
            x = p.x - cam + ox
            y = p.y + oy
            if not (-40 < x < W + 40 and -40 < y < H + 40):
                continue
            f = clamp(p.life / p.max_life, 0.0, 1.0)
            size = max(1, int(p.size * (0.4 + 0.6 * f)))
            col = (int(p.color[0] * f), int(p.color[1] * f), int(p.color[2] * f))
            if p.add:
                pygame.draw.circle(c, col, (int(x), int(y)), size)
            else:
                pygame.draw.circle(c, col, (int(x), int(y)), size)

    def draw_hud(self):
        c = self.canvas
        th = self.theme
        sim = self.sim
        pct = int(round(sim.progress() * 100))

        bar_w, bar_h = 520, 16
        bx = (W - bar_w) // 2
        by = 26
        track = pygame.Surface((bar_w, bar_h), pygame.SRCALPHA)
        pygame.draw.rect(track, (255, 255, 255, 28), (0, 0, bar_w, bar_h), border_radius=8)
        pygame.draw.rect(track, (255, 255, 255, 60), (0, 0, bar_w, bar_h), 1, border_radius=8)
        c.blit(track, (bx, by))

        fill = int(bar_w * sim.progress())
        if fill > 2:
            fill_surf = pygame.Surface((fill, bar_h), pygame.SRCALPHA)
            pygame.draw.rect(fill_surf, (*th["accent"], 235), (0, 0, fill, bar_h),
                             border_radius=8)
            c.blit(fill_surf, (bx, by))
            blit_glow(c, 34, th["accent"], (bx + fill, by + bar_h // 2), 0.9)

        blit_text(c, self.font_small, f"{pct}%", th["accent"], (W // 2, by + bar_h + 18))
        blit_text(c, self.font_small, self.level.name.upper(), (235, 235, 255),
                  (bx, by + bar_h + 16), "topright")
        blit_text(c, self.font_small, f"INTENTO {self.attempts:02d}", (200, 200, 225),
                  (W - bx, by + bar_h + 16), "topleft")

        blit_text(c, self.font_small, MODE_NAMES[sim.mode], th["accent"],
                  (bx - 22, by + bar_h / 2), "midright")

        if self.practice:
            blit_text(c, self.font_small,
                      f"PRACTICA · {len(self.checkpoints)} puntos · Z guardar · X quitar · P normal",
                      (90, 255, 180), (W // 2, 106))

        estado_musica = "OFF" if self.sfx.muted else "ON"
        blit_text(c, self.font_tiny,
                  "ESPACIO saltar / impulsar / girar   R reiniciar   ESC pausa"
                  f"   M musica: {estado_musica}",
                  (170, 170, 200), (W // 2, H - 22), "center")

    def draw(self):
        c = self.canvas
        self.canvas.fill((0, 0, 0))

        ox = random.uniform(-self.shake, self.shake) if self.shake > 0.2 else 0.0
        oy = random.uniform(-self.shake, self.shake) if self.shake > 0.2 else 0.0

        if self.state == MENU:
            self.draw_menu()
            return

        self.draw_background()
        cam = self.cam
        self.draw_level(cam)
        if self.practice and self.checkpoints:
            point = self.checkpoints[-1]
            px = int(point["x"] - cam + point["hit_w"] / 2)
            py = int(point["y"] + point["hit_h"] / 2)
            pygame.draw.circle(c, (90, 255, 180), (px, py), 24, 3)
            pygame.draw.line(c, (90, 255, 180), (px, py - 32), (px, py + 32), 2)
        self.draw_particles(cam, ox, oy)
        self.draw_player(cam, ox, oy)
        self.draw_hud()

        if self.state == PAUSE:
            veil = pygame.Surface((W, H), pygame.SRCALPHA)
            veil.fill((5, 4, 14, 190))
            c.blit(veil, (0, 0))
            blit_text(c, self.font_big, "PAUSA", (255, 255, 255), (W / 2, H / 2 - 70),
                      "center", glow=self.theme["accent"])
            blit_text(c, self.font_mid, "ESC continuar    R reiniciar    Q menu",
                      (210, 210, 235), (W / 2, H / 2 + 10))
            blit_text(c, self.font_small, "P cambiar modo (reinicia) · Z guardar punto · X quitar · M sonido", (160, 160, 190),
                      (W / 2, H / 2 + 56))

        if self.state == WIN:
            veil = pygame.Surface((W, H), pygame.SRCALPHA)
            veil.fill((5, 4, 14, 120))
            c.blit(veil, (0, 0))
            blit_text(c, self.font_big, "PRACTICA COMPLETADA" if self.practice else "NIVEL COMPLETADO", (255, 255, 255), (W / 2, 250),
                      "center", glow=self.theme["accent"])
            blit_text(c, self.font_mid, f"{self.level.name}  ·  {self.attempts} " + ("intento" if self.attempts == 1 else "intentos"),
                      self.theme["accent"], (W / 2, 330))
            if self.win_t > 0.5:
                a = abs(math.sin(self.t * 3.0))
                blit_text(c, self.font_mid, "ESPACIO para volver al menu",
                          (int(200 * a + 55), int(200 * a + 55), 230),
                          (W / 2, 460), "center")

        if self.flash > 0.01:
            f = pygame.Surface((W, H), pygame.SRCALPHA)
            f.fill((255, 40, 90, int(40 * self.flash)))
            c.blit(f, (0, 0))

    # -- menu ---------------------------------------------------------------
    def draw_menu(self):
        c = self.canvas
        th = self.theme
        self.draw_background()

        # cubos decorativos flotando
        for i in range(7):
            x = (i * 210 + self.t * (30 + i * 9)) % (W + 160) - 80
            y = 150 + 60 * math.sin(self.t * 0.9 + i * 1.3) + i * 42
            img = pygame.transform.rotozoom(self.img_cube_small, math.sin(self.t + i) * 18, 1.0)
            c.blit(img, img.get_rect(center=(x, y)))

        veil = pygame.Surface((W, H), pygame.SRCALPHA)
        veil.fill((6, 5, 18, 130))
        c.blit(veil, (0, 0))

        blit_text(c, self.font_title, TITLE, (255, 255, 255), (W / 2, 132), "center",
                  glow=th["accent"])
        blit_text(c, self.font_small, "un homenaje a Geometry Dash · Python + pygame",
                  (185, 190, 220), (W / 2, 196), "center")

        card_w, card_h = 292, 200
        gap = 20
        self.card_rects = []
        page = self.sel // 4
        visible = list(enumerate(LEVELS))[page * 4:page * 4 + 4]
        total = len(visible) * card_w + (len(visible) - 1) * gap
        x0 = (W - total) / 2
        y0 = 266

        for slot, (i, lvl) in enumerate(visible):
            x = x0 + slot * (card_w + gap)
            selected = i == self.sel
            self.card_rects.append((i, pygame.Rect(int(x), int(y0), card_w, card_h)))
            rec = self.records.get(lvl.name, {"best": 0, "done": False})
            card = pygame.Surface((card_w, card_h), pygame.SRCALPHA)
            pygame.draw.rect(card, (16, 14, 34, 225), (0, 0, card_w, card_h), border_radius=18)
            edge = lvl.theme["accent"] if selected else (70, 70, 110)
            width = 3 if selected else 1
            pygame.draw.rect(card, edge, (0, 0, card_w, card_h), width, border_radius=18)
            c.blit(card, (x, y0))

            if selected:
                pulse = 0.55 + 0.45 * abs(math.sin(self.t * 2.2))
                blit_glow(c, 150, lvl.theme["accent"],
                          (x + card_w / 2, y0 + card_h / 2), 0.35 * pulse)

            blit_text(c, self.font_card, lvl.name.upper(), (250, 250, 255),
                      (x + 22, y0 + 30), "midleft")
            blit_text(c, self.font_tiny, lvl.difficulty.upper(), lvl.theme["accent"],
                      (x + 22, y0 + 66), "midleft")
            blit_text(c, self.font_tiny, lvl.subtitle, (175, 178, 205),
                      (x + 22, y0 + 94), "midleft")

            # progreso del jugador
            bw, bh = card_w - 44, 10
            bx, by = x + 22, y0 + 126
            pygame.draw.rect(c, (44, 42, 70), (bx, by, bw, bh), border_radius=5)
            fill = int(bw * rec.get("best", 0) / 100)
            if fill > 0:
                pygame.draw.rect(c, lvl.theme["accent"], (bx, by, fill, bh), border_radius=5)
            label = "COMPLETADO" if rec.get("done") else f"MEJOR {rec.get('best', 0)}%"
            blit_text(c, self.font_tiny, label, (190, 190, 215), (bx, by + 26), "midleft")

            if selected:
                blit_text(c, self.font_tiny, "ENTER / ESPACIO jugar", lvl.theme["accent"],
                          (x + card_w - 22, y0 + card_h - 20), "bottomright")

        blit_text(c, self.font_small,
                  "P  modo: " + ("PRACTICA · Z punto de control · X quitar" if self.practice
                                  else "NORMAL · activa practica para entrenar"),
                  (90, 255, 180) if self.practice else (185, 190, 220),
                  (W / 2, 510))
        blit_text(c, self.font_tiny, f"NIVEL {self.sel + 1} / {len(LEVELS)} · PAGINA {page + 1} / {(len(LEVELS) + 3) // 4}",
                  th["accent"], (W / 2, 660))
        blit_text(c, self.font_mid, "<  >  elegir nivel    ESPACIO  jugar    M  musica    ESC  salir",
                  (200, 200, 225), (W / 2, 560), "center")
        blit_text(c, self.font_tiny, "ESPACIO saltar · R reiniciar · ESC pausa · M musica · F11 pantalla completa",
                  (140, 142, 170), (W / 2, 620), "center")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    game = Game()

    if "--selftest" in argv:
        game.start()
        for i in range(240):
            game.update(1.0 / 60.0)
            game.draw()
            game.present()
            if i == 100:
                game.respawn()
        game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        game.update(1.0 / 60.0)
        game.draw()
        game.present()
        print("selftest ok")
        pygame.quit()
        return 0

    running = True
    while running:
        dt = min(game.clock.tick(FPS) / 1000.0, 0.05)
        for ev in pygame.event.get():
            if not game.handle_event(ev):
                running = False
        game.update(dt)
        game.draw()
        game.present()

    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
