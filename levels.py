"""Datos y construccion de los niveles de Neon Dash.

Las coordenadas de autoria estan en celdas de ``TILE`` pixeles.
``row=0`` es la fila que descansa sobre el suelo; los valores crecen hacia
arriba.  Al construir el nivel se convierten a pixeles del mundo.

Tipos de objeto
---------------
- ``spike`` / ``spike_down``: pinchos en el suelo o colgando del techo.
- ``block``: solido (se puede aterrizar encima, mata de lado).
- ``saw``: sierra circular de 2x2.
- ``saw_move``: sierra que sube y baja por un carril.
- ``pad``: rampa de impulso que lanza al cubo muy alto.
- ``pit``: vacio en el suelo; si caes, la lava te mata.
- ``tower``: torre de bloques que sale de la lava (escalera).
- ``orb_y`` / ``orb_p`` / ``orb_b``: orbes de salto (amarillo, rosa, azul).
- ``portal_ship`` / ``portal_ball`` / ``portal_cube``: puertas de cambio de modo.

El salto del cubo recorre ~183 px, asi que los obstaculos consecutivos deben
estar a 5 celdas o mas.  Las secciones de nave y bola necesitan su techo.
``verify.py`` comprueba que los niveles se puedan terminar.
"""

import math

TILE = 40
GROUND_Y = 596

# Altura del techo de las secciones especiales (fila de bloques).
SHIP_CEIL = 8
BALL_CEIL = 5


class Obj:
    """Un objeto del nivel ya convertido a pixeles del mundo."""

    __slots__ = ("kind", "x", "y", "w", "h", "meta")

    def __init__(self, kind, x, y, w, h, meta=None):
        self.kind = kind
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.meta = meta

    def __repr__(self):
        return f"Obj({self.kind!r}, {self.x}, {self.y}, {self.w}, {self.h})"


class LevelBuilder:
    """Ayudante para escribir niveles en coordenadas de rejilla."""

    def __init__(self):
        self.objs = []

    def _put(self, kind, col, row, w, h, meta=None):
        # (col, row) es la esquina inferior izquierda de la pieza.
        x = col * TILE
        y = GROUND_Y - (row + h) * TILE
        self.objs.append(Obj(kind, x, y, w * TILE, h * TILE, meta))

    def spike(self, col, n=1, row=0, down=False):
        for i in range(n):
            self._put("spike_down" if down else "spike", col + i, row, 1, 1)
        return self

    def block(self, col, row=0, w=1, h=1):
        self._put("block", col, row, w, h)
        return self

    def platform(self, col, w=3, row=0):
        self.block(col, row, w, 1)
        return self

    def saw(self, col, row=0):
        self._put("saw", col, row, 2, 2)
        return self

    def saw_move(self, col, row=0, amp=2, period=2.2, phase=0.0):
        """Sierra que oscila ``amp`` celdas arriba y abajo."""
        self._put("saw_move", col, row, 2, 2,
                  {"amp": amp * TILE, "omega": math.tau / period,
                   "phase": phase})
        return self

    def pad(self, col, row=0):
        """Rampa de impulso en el suelo."""
        self._put("pad", col, row, 1, 1)
        return self

    def pit(self, col, width):
        """Vacio sin suelo; debajo hay lava."""
        self.objs.append(Obj("pit", col * TILE, GROUND_Y, width * TILE, 1))
        return self

    def tower(self, col, height, width=2):
        """Torre que nace en la lava y sobresale ``height`` celdas."""
        self._put("block", col, -1, width, height + 1)
        return self

    def slab(self, col, row, width=3):
        """Losa flotante de una celda de grosor."""
        self.block(col, row, width, 1)
        return self

    def orb(self, col, row, kind="y"):
        self._put("orb_" + kind, col, row, 1, 1)
        return self

    def portal(self, col, mode, row=0):
        self._put("portal_" + mode, col, row, 1, 3)
        return self

    def ceiling(self, col, w, row=SHIP_CEIL):
        self.block(col, row, w, 1)
        return self


class Cursor:
    """Coloca patrones en secuencia y avanza la columna actual."""

    def __init__(self, builder, col):
        self.b = builder
        self.col = col

    def spike(self, n=1, gap=6, row=0, down=False):
        self.b.spike(self.col, n, row, down)
        self.col += n + gap
        return self

    def saw(self, gap=6, row=0):
        self.b.saw(self.col, row)
        self.col += 2 + gap
        return self

    def platform(self, w=3, gap=6, row=0):
        self.b.platform(self.col, w, row)
        self.col += w + gap
        return self

    def block(self, w=1, h=1, gap=6, row=0):
        self.b.block(self.col, row, w, h)
        self.col += w + gap
        return self

    def orb(self, kind="y", row=3, gap=0):
        self.b.orb(self.col, row, kind)
        self.col += 1 + gap
        return self

    def wait(self, n=1):
        self.col += n
        return self


def orb_jump(b, col, n=5, kind="y", row=2):
    """Tanda de pinchos con un orbe alto para alargar el salto.

    El orbe va sobre el centro de la tanda, a la altura de la cabeza: hay que
    saltar y volver a pulsar al pasar por encima para encadenar otro salto.
    """
    b.spike(col, n)
    b.orb(col + n // 2, row, kind)


def build(features, start=9, gap=6):
    """Coloca una lista de patrones separados por ``gap`` celdas."""
    b = LevelBuilder()
    col = start
    for kind, size in features:
        if kind == "spike":
            b.spike(col, size)
            width = size
        elif kind == "saw":
            b.saw(col)
            width = 2
        elif kind == "platform":
            b.platform(col, size)
            width = size
        else:
            raise ValueError(kind)
        col += width + gap
    return b, col


class Level:
    def __init__(self, name, subtitle, difficulty, theme, objs, finish_col):
        self.name = name
        self.subtitle = subtitle
        self.difficulty = difficulty
        self.theme = theme
        self.finish_x = finish_col * TILE
        self.length = self.finish_x
        self.objs = objs
        self.blocks = [o for o in objs if o.kind == "block"]
        self.spikes = [o for o in objs if o.kind in ("spike", "spike_down")]
        self.saws = [o for o in objs if o.kind == "saw"]
        self.moving_saws = [o for o in objs if o.kind == "saw_move"]
        self.pads = [o for o in objs if o.kind == "pad"]
        self.pits = [o for o in objs if o.kind == "pit"]
        self.orbs = [o for o in objs if o.kind.startswith("orb_")]
        self.portals = [o for o in objs if o.kind.startswith("portal_")]


THEMES = {
    "neon": {
        "sky_top": (9, 9, 26),
        "sky_bottom": (44, 16, 72),
        "accent": (0, 230, 255),
        "accent2": (255, 48, 150),
        "ground": (17, 14, 36),
        "stripe": (33, 26, 64),
        "far": (26, 20, 54),
        "near": (40, 28, 74),
        "block": (44, 38, 88),
        "block_edge": (120, 110, 200),
        "spike": (255, 60, 150),
        "player": (0, 235, 255),
        "style": "sun",
    },
    "violet": {
        "sky_top": (22, 8, 24),
        "sky_bottom": (74, 18, 52),
        "accent": (255, 150, 40),
        "accent2": (190, 70, 255),
        "ground": (28, 12, 30),
        "stripe": (52, 22, 52),
        "far": (44, 16, 44),
        "near": (66, 24, 60),
        "block": (62, 28, 66),
        "block_edge": (200, 130, 210),
        "spike": (255, 176, 48),
        "player": (255, 160, 70),
        "style": "rings",
    },
    "orbit": {
        "sky_top": (4, 16, 30),
        "sky_bottom": (10, 54, 76),
        "accent": (60, 255, 210),
        "accent2": (120, 150, 255),
        "ground": (8, 22, 34),
        "stripe": (18, 44, 60),
        "far": (14, 34, 52),
        "near": (22, 52, 74),
        "block": (22, 52, 74),
        "block_edge": (110, 220, 230),
        "spike": (70, 255, 190),
        "player": (80, 255, 210),
        "style": "orbit",
    },
    "inferno": {
        "sky_top": (26, 6, 10),
        "sky_bottom": (86, 20, 18),
        "accent": (255, 90, 60),
        "accent2": (255, 200, 80),
        "ground": (30, 10, 12),
        "stripe": (58, 20, 20),
        "far": (52, 14, 16),
        "near": (78, 22, 22),
        "block": (74, 24, 24),
        "block_edge": (255, 160, 110),
        "spike": (255, 96, 60),
        "player": (255, 110, 70),
        "style": "embers",
    },
}


# --------------------------------------------------------------------------- #
# Secciones reutilizables
# --------------------------------------------------------------------------- #

def ship_section(b, start, end, obstacles):
    """Corredor de nave: techo de bloques y obstaculos alternos.

    ``obstacles`` es una lista de ``(col, tipo)`` con tipo:
    ``"pf"`` pilar desde el suelo (3 de alto), ``"pc"`` pilar desde el techo,
    ``"sf"`` sierra en el suelo, ``"sc"`` sierra en el techo.
    """
    b.portal(start, "ship")
    b.ceiling(start, end - start + 4, SHIP_CEIL)
    for col, kind in obstacles:
        if kind == "pf":
            b.block(col, 0, 1, 3)                      # 476..596
        elif kind == "pc":
            b.block(col, SHIP_CEIL - 3, 1, 3)          # 276..396
        elif kind == "sf":
            b.saw(col, 0)
        elif kind == "sc":
            b.saw(col, SHIP_CEIL - 2)                  # 276..356
    return b


def ball_section(b, start, end, floor_spikes, ceil_spikes):
    """Corredor de bola: techo bajo y pinchos en ambas superficies."""
    b.portal(start, "ball")
    b.ceiling(start, end - start + 4, BALL_CEIL)
    for col in floor_spikes:
        b.spike(col)
    for col in ceil_spikes:
        b.spike(col, row=BALL_CEIL - 1, down=True)
    return b


def _finish(b, c, name, subtitle, difficulty, theme):
    return Level(name, subtitle, difficulty, theme, b.objs, c.col + 6)


# --------------------------------------------------------------------------- #
# Niveles
# --------------------------------------------------------------------------- #

def _level_one():
    """Stereo Neon: cubo puro, rampas de impulso y orbes."""
    b = LevelBuilder()

    b.spike(9)
    b.spike(16)
    b.spike(23, 2)
    b.platform(31, 3)
    b.spike(40, 2)
    b.saw(48)
    b.spike(56)

    # rampa + campo de pinchos
    b.pad(63)
    b.spike(64, 5)

    b.spike(75)
    orb_jump(b, 82, 5)
    b.platform(93, 4)
    b.spike(103, 2)
    b.saw(111)
    b.spike(119)

    orb_jump(b, 126, 4, kind="p")
    b.spike(137)
    b.platform(144, 3)
    b.spike(153)
    b.saw(161)
    b.spike(169, 2)
    b.spike(178)
    b.spike(186, 2)

    return Level("Stereo Neon", "Rampas, orbes y ritmo tranquilo", "Facil",
                 THEMES["neon"], b.objs, 195)


def _level_two():
    """Violeta Salvaje: nave temprana, rampa y orbe rosa."""
    b = LevelBuilder()

    # calentamiento corto antes de la nave
    b.spike(9)
    b.spike(16, 2)
    b.platform(24, 3)

    # nave temprana: esta es la identidad del nivel
    ship_start = 32
    ship_end = ship_start + 34
    ship_section(b, ship_start, ship_end, [
        (ship_start + 8, "pf"),
        (ship_start + 15, "sc"),
        (ship_start + 21, "sf"),
        (ship_start + 27, "pc"),
    ])
    b.saw_move(ship_start + 12, 0, amp=1.5, period=2.4)
    b.saw_move(ship_start + 24, SHIP_CEIL - 2, amp=1.5, period=2.8, phase=1.2)
    b.portal(ship_end + 4, "cube")

    b.spike(78)
    b.spike(86, 2)
    b.platform(94, 3)
    b.spike(103, 2)

    b.pad(110)
    b.spike(111, 5)

    b.spike(122, 2)
    b.saw(130)
    b.spike(138)
    orb_jump(b, 145, 5)
    b.platform(157, 4)
    b.spike(167)
    b.spike(175, 2)
    b.saw(183)
    b.spike(191)

    orb_jump(b, 198, 4, kind="p")
    b.platform(209, 3)
    b.spike(218)
    b.saw(226)
    b.spike(234, 2)

    return Level("Violeta Salvaje", "Nave temprana, rampa y orbe rosa", "Normal",
                 THEMES["violet"], b.objs, 243)


def _level_three():
    """Orbita Rota: sierra movil, cadena de orbes, nave y bola."""
    b = LevelBuilder()

    b.spike(10)
    b.platform(18, 2)
    b.spike(27, 2)
    b.saw_move(38, 0, amp=1.5, period=2.4)
    b.spike(48)

    # cadena de dos orbes sobre nueve pinchos
    b.spike(55, 9)
    b.orb(57, 2)
    b.orb(60, 2)

    b.spike(74)
    b.spike(82, 2)
    b.saw(90)
    b.spike(98)

    # nave
    ship_start = 106
    ship_end = ship_start + 40
    ship_section(b, ship_start, ship_end, [
        (ship_start + 7, "pf"),
        (ship_start + 14, "sc"),
        (ship_start + 21, "pf"),
        (ship_start + 28, "sc"),
        (ship_start + 33, "sf"),
    ])
    b.saw_move(ship_start + 11, 0, amp=1.5, period=2.4)
    b.saw_move(ship_start + 25, SHIP_CEIL - 2, amp=1.6, period=2.8, phase=0.8)
    b.portal(ship_end + 4, "cube")

    b.spike(158)
    b.spike(166, 2)
    b.platform(174, 3)
    b.spike(183)

    # bola
    ball_start = 190
    ball_end = ball_start + 46
    ball_section(b, ball_start, ball_end,
                 floor_spikes=[ball_start + 8, ball_start + 20,
                               ball_start + 32, ball_start + 42],
                 ceil_spikes=[ball_start + 14, ball_start + 26,
                              ball_start + 38])
    b.portal(ball_end + 4, "cube")

    b.spike(248, 2)
    b.platform(257, 3)
    b.spike(266)
    b.spike(274, 2)
    b.pad(282)
    b.spike(283, 5)

    return Level("Orbita Rota", "Sierra, orbes, nave y bola", "Dificil",
                 THEMES["orbit"], b.objs, 294)


def _level_four():
    """Caos Final: bola, rampas, cadena de orbes y nave densa."""
    b = LevelBuilder()

    b.spike(9)
    b.saw_move(17, 0, amp=1.5, period=2.0)
    b.spike(26, 2)
    b.spike(34)

    # bola de entrada
    ball_start = 47
    ball_end = ball_start + 50
    ball_section(b, ball_start, ball_end,
                 floor_spikes=[ball_start + 8, ball_start + 19,
                               ball_start + 30, ball_start + 41,
                               ball_start + 49],
                 ceil_spikes=[ball_start + 13, ball_start + 24,
                              ball_start + 35, ball_start + 46])
    b.portal(ball_end + 4, "cube")

    b.spike(109)
    b.spike(117, 2)
    b.pad(125)
    b.spike(126, 5)

    b.spike(137, 2)
    b.saw(145)
    b.spike(153)

    # cadena de orbes
    b.spike(161, 9)
    b.orb(163, 2)
    b.orb(166, 2)

    b.spike(180, 2)
    b.platform(188, 3)
    b.spike(197)
    b.saw(205)

    # nave densa
    ship_start = 213
    ship_end = ship_start + 46
    ship_section(b, ship_start, ship_end, [
        (ship_start + 6, "pf"),
        (ship_start + 12, "sc"),
        (ship_start + 17, "sf"),
        (ship_start + 22, "pc"),
        (ship_start + 28, "pf"),
        (ship_start + 34, "sc"),
        (ship_start + 39, "sf"),
    ])
    b.saw_move(ship_start + 9, 0, amp=1.5, period=2.4)
    b.saw_move(ship_start + 19, SHIP_CEIL - 2, amp=1.5, period=2.7, phase=1.1)
    b.saw_move(ship_start + 31, 0, amp=1.8, period=3.0, phase=0.4)
    b.portal(ship_end + 4, "cube")

    b.spike(271, 2)
    b.spike(280)
    b.saw(288)
    b.spike(296, 2)
    b.platform(305, 4)
    b.spike(316)
    b.spike(324, 2)
    b.pad(333)
    b.spike(334, 5)

    return Level("Caos Final", "Bola, orbes y nave sin respiro", "Extremo",
                 THEMES["inferno"], b.objs, 346)


def lava_stairs(b, start, floating=False, heights=(1, 2, 3, 2, 1)):
    """Cinco peldaños separados por huecos reales sobre una piscina de lava."""
    b.pit(start - 1, 27)
    for offset, height in zip((0, 5, 10, 15, 20), heights):
        if floating:
            b.slab(start + offset, height - 1, 3)
        else:
            b.tower(start + offset, height, 3)
    return start + 26


def lava_slabs(b, start):
    """Losas con anchos y alturas distintos; no hay suelo entre ellas."""
    b.pit(start - 1, 29)
    for offset, row, width in ((0, 0, 4), (6, 1, 3), (11, 1, 4),
                               (17, 0, 3), (22, 0, 4)):
        b.slab(start + offset, row, width)
    return start + 28


def ramp_crossing(b, start):
    """Rampa que cruza un hueco de lava y aterriza en una losa."""
    b.pad(start)
    b.pit(start + 1, 6)
    b.slab(start + 7, 0, 4)
    b.spike(start + 17)
    return start + 24


def terrain_remix(level, start, kind):
    # Cambia un tramo de cubo existente, conservando las secciones de otros modos.
    level.objs[:] = [o for o in level.objs if not start - 5 <= o.x / TILE < start + 40]
    b = LevelBuilder()
    (lava_stairs if kind == "stairs" else lava_slabs)(b, start)
    objects = level.objs + b.objs
    return Level(level.name, level.subtitle, level.difficulty,
                 level.theme, objects, level.finish_x / TILE)


def _level_five():
    b = LevelBuilder()
    b.platform(10, 4)
    lava_stairs(b, 22)
    b.spike(55, 2)
    ramp_crossing(b, 64)
    lava_slabs(b, 98)
    b.saw(134)
    lava_stairs(b, 148, floating=True, heights=(1, 2, 2, 3, 2))
    b.spike(182)
    b.pad(190)
    b.spike(191, 5)
    return Level("Escalera Solar", "Peldaños separados sobre lava", "Normal",
                 THEMES["neon"], b.objs, 207)


def _level_six():
    b = LevelBuilder()
    ramp_crossing(b, 12)
    lava_slabs(b, 46)
    b.spike(83)
    ship_section(b, 94, 132, [(103, "pf"), (113, "sc"), (123, "pf")])
    b.portal(136, "cube")
    lava_stairs(b, 151, floating=True, heights=(1, 1, 2, 3, 2))
    b.spike(187, 2)
    ramp_crossing(b, 198)
    return Level("Islas de Magma", "Losas flotantes y vuelo entre islas", "Dificil",
                 THEMES["inferno"], b.objs, 231)


def _level_seven():
    b = LevelBuilder()
    lava_stairs(b, 12)
    b.spike(47)
    ball_section(b, 58, 102, [66, 78, 90, 100], [72, 84, 96])
    b.portal(106, "cube")
    ramp_crossing(b, 120)
    lava_slabs(b, 154)
    b.spike(191, 2)
    lava_stairs(b, 204, floating=True, heights=(1, 2, 3, 3, 2))
    orb_jump(b, 242, 5)
    b.saw_move(258, 0, amp=1, period=2.6)
    return Level("Ruta Fragmentada", "Escaleras, gravedad y saltos de lava", "Dificil",
                 THEMES["orbit"], b.objs, 275)


LEVELS = [terrain_remix(_level_one(), 91, "stairs"),
          terrain_remix(_level_two(), 155, "slabs"),
          terrain_remix(_level_three(), 250, "stairs"),
          terrain_remix(_level_four(), 275, "slabs"),
          _level_five(), _level_six(), _level_seven()]
