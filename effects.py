#!/usr/bin/env python3
"""Thirty-two effects of my own, for the Trident Z Royal sticks.

An effect is a pure function of time:

    fn(t, sticks, leds, colours) -> [[(r, g, b), ...], ...]

`colours` is the palette chosen in the panel; each effect declares how many
slots it uses (1-3) and what they default to, so two-colour effects really do
give you two pickers. Nothing is kept between frames, so any effect can start,
stop or be re-entered at any moment and still paints a coherent picture.

The 8 sticks x 8 LEDs are treated as an 8x8 grid where that helps, and as
eight independent columns where that reads better. A handful read the real
machine - load, temperature, memory, disk, network - so the sticks show
something true rather than invented.
"""
import math
import time

GREEN = (0, 255, 65)
CRIMSON = (220, 20, 60)
WHITE = (255, 255, 255)
AMBER = (255, 165, 0)
ICE = (143, 214, 255)
VIOLET = (138, 43, 226)
LIME = (150, 255, 120)


# ------------------------------------------------------------------ helpers
def _hash(*values):
    h = 2166136261
    for value in values:
        h = (h ^ (int(value) & 0xFFFFFFFF)) * 16777619 & 0xFFFFFFFF
    return (h >> 8) / 16777215.0


def _c(colours, index, fallback):
    try:
        return tuple(colours[index])
    except (IndexError, TypeError):
        return fallback


def _mix(first, second, amount):
    amount = max(0.0, min(1.0, amount))
    return tuple(int(first[i] + (second[i] - first[i]) * amount) for i in range(3))


def _scale(colour, amount):
    amount = max(0.0, min(1.0, amount))
    return tuple(int(channel * amount) for channel in colour)


def _blank(sticks, leds, level=0.0, colour=GREEN):
    return [[_scale(colour, level) for _ in range(leds)] for _ in range(sticks)]


def _cached(key, interval, reader):
    entry = _CACHE.get(key)
    now = time.monotonic()
    if entry and now - entry[0] < interval:
        return entry[1]
    try:
        value = reader()
    except Exception:  # noqa: BLE001
        value = entry[1] if entry else 0.0
    _CACHE[key] = (now, value)
    return value


_CACHE = {}
_LAST = {}


# ------------------------------------------------------------------ weather
def binary_rain(t, sticks, leds, colours):
    """Digits falling, bright head, dim tail."""
    trail, head_colour = _c(colours, 0, GREEN), _c(colours, 1, WHITE)
    frame = []
    for stick in range(sticks):
        speed = 4.5 + _hash(stick, 7) * 3.0
        column = []
        for led in range(leds):
            level, colour = 0.0, trail
            for drop in range(2):
                phase = _hash(stick, drop, 11) * (leds + 6)
                head = (t * speed + phase + drop * 5) % (leds + 6)
                distance = (head - led) % (leds + 6)
                if distance < 1.0:
                    level, colour = 1.0, head_colour
                elif distance < 5.0:
                    fade = (5.0 - distance) / 4.0
                    if fade > level:
                        level, colour = fade * 0.85, trail
            column.append(_scale(colour, level * (0.55 + 0.45 * _hash(stick, led))))
        frame.append(column)
    return frame


def embers(t, sticks, leds, colours):
    """Sparks flaring and fading like blown coals."""
    first, second = _c(colours, 0, WHITE), _c(colours, 1, CRIMSON)
    frame = _blank(sticks, leds, 0.02, first)
    tick = int(t * 9)
    for stick in range(sticks):
        for led in range(leds):
            for seed in (0, 1):
                if _hash(stick, led, seed, tick // 3) > 0.985:
                    age = (tick % 3) / 3.0
                    frame[stick][led] = _scale(first if seed == 0 else second, (1.0 - age) ** 2)
    return frame


def aurora(t, sticks, leds, colours):
    """Slow curtains of two colours drifting across the kit."""
    first, second = _c(colours, 0, GREEN), _c(colours, 1, VIOLET)
    frame = []
    for stick in range(sticks):
        column = []
        for led in range(leds):
            a = math.sin(t * 0.6 + stick * 0.8 + led * 0.2)
            b = math.sin(t * 0.37 - stick * 0.55 + led * 0.5)
            curtain = max(0.0, a * 0.6 + b * 0.4)
            column.append(_scale(_mix(first, second, max(0.0, b)), 0.08 + curtain ** 2 * 0.9))
        frame.append(column)
    return frame


def lightning(t, sticks, leds, colours):
    """Dark, then a jagged flash that walks across the sticks."""
    bolt = _c(colours, 0, WHITE)
    frame = _blank(sticks, leds, 0.03)
    burst = int(t * 2.0)
    if _hash(burst, 5) > 0.45:
        age = (t * 2.0) % 1.0
        if age < 0.35:
            column_hit = int(_hash(burst, 9) * sticks)
            for led in range(leds):
                jag = int(_hash(burst, led) * 2) - 1
                x = max(0, min(sticks - 1, column_hit + jag))
                frame[x][led] = _scale(bolt, (1.0 - age / 0.35) * 0.95)
    return frame


def candle(t, sticks, leds, colours):
    """Per-stick warm flicker, each one breathing at its own rate."""
    flame = _c(colours, 0, AMBER)
    frame = []
    for stick in range(sticks):
        flicker = 0.55 + 0.45 * _hash(stick, int(t * 14))
        sway = 0.5 + 0.5 * math.sin(t * 3.1 + stick * 1.7)
        column = []
        for led in range(leds):
            near = 1.0 - led / max(leds, 1)
            column.append(_scale(flame, flicker * (0.25 + 0.75 * near) * (0.7 + 0.3 * sway)))
        frame.append(column)
    return frame


def tide(t, sticks, leds, colours):
    """A slow crest rolling diagonally between two colours."""
    trough, crest = _c(colours, 0, GREEN), _c(colours, 1, CRIMSON)
    frame = []
    for stick in range(sticks):
        column = []
        for led in range(leds):
            wave = 0.5 + 0.5 * math.sin(t * 1.1 - stick * 0.55 - led * 0.35)
            column.append(_scale(_mix(trough, crest, wave ** 1.6), 0.20 + 0.80 * wave ** 2))
        frame.append(column)
    return frame


def snowfall(t, sticks, leds, colours):
    """Flakes drifting down, trailing a second colour."""
    flake, tail_colour = _c(colours, 0, WHITE), _c(colours, 1, ICE)
    frame = _blank(sticks, leds, 0.02, tail_colour)
    for stick in range(sticks):
        speed = 1.6 + _hash(stick, 3) * 1.4
        for flake_index in range(2):
            position = (t * speed + _hash(stick, flake_index) * leds) % leds
            led = int(position)
            frame[stick][led] = _scale(flake, 0.9)
            frame[stick][(led + 1) % leds] = _scale(tail_colour, 0.35)
    return frame


def starfield(t, sticks, leds, colours):
    """Stars streaking outward, bright and dim colours."""
    bright, dim = _c(colours, 0, WHITE), _c(colours, 1, ICE)
    frame = _blank(sticks, leds, 0.02)
    count = int(t * 7)
    for index in range(count, count + 8):
        stick = int(_hash(index, 1) * sticks)
        led = int(_hash(index, 2) * leds)
        age = _hash(index, 3)
        frame[stick][led] = _scale(bright if age > 0.7 else dim, 0.4 + age * 0.6)
    return frame


def fireflies(t, sticks, leds, colours):
    """A few lazy points wandering, blinking on and off."""
    glow = _c(colours, 0, LIME)
    frame = _blank(sticks, leds, 0.02)
    for index in range(4):
        x = int((0.5 + 0.5 * math.sin(t * (0.4 + index * 0.13) + index)) * (sticks - 1))
        y = int((0.5 + 0.5 * math.cos(t * (0.31 + index * 0.17) + index * 2)) * (leds - 1))
        blink = 0.5 + 0.5 * math.sin(t * 2.3 + index * 1.9)
        frame[x][y] = _scale(glow, 0.25 + blink * 0.75)
    return frame


def fog(t, sticks, leds, colours):
    """A haze breathing through the whole kit."""
    haze = _c(colours, 0, GREEN)
    drift = 0.5 + 0.5 * math.sin(t * 0.35)
    frame = []
    for stick in range(sticks):
        column = []
        for led in range(leds):
            cloud = 0.5 + 0.5 * math.sin(t * 0.5 + stick * 0.4 + led * 0.55)
            level = (0.10 + 0.30 * cloud) * (0.5 + 0.5 * drift)
            column.append(_scale(_mix(haze, (90, 120, 100), 0.55), level))
        frame.append(column)
    return frame


# ------------------------------------------------------------------ motion
def heartbeat(t, sticks, leds, colours):
    """Two thumps, then a held glow."""
    pulse = _c(colours, 0, CRIMSON)
    cycle = 1.35
    position = (t % cycle) / cycle
    beat = 0.0
    for centre, weight in ((0.02, 1.0), (0.20, 0.72)):
        distance = abs(position - centre)
        if distance < 0.10:
            beat = max(beat, weight * math.cos(distance / 0.10 * math.pi / 2) ** 2)
    base = 0.18 + 0.12 * math.sin(t * 1.4)
    frame = []
    for stick in range(sticks):
        column = []
        for led in range(leds):
            reach = 1.0 - abs(led - (leds - 1) / 2) / max(leds, 1)
            column.append(_scale(pulse, base + beat * (0.55 + 0.45 * reach)))
        frame.append(column)
    return frame


def serpent(t, sticks, leds, colours):
    """A body circling each stick with a bright head."""
    body, head_colour = _c(colours, 0, GREEN), _c(colours, 1, CRIMSON)
    frame = []
    for stick in range(sticks):
        head = (t * (5.0 + _hash(stick, 5) * 1.5) + stick * 0.9) % leds
        column = []
        for led in range(leds):
            distance = (head - led) % leds
            if distance < 1.0:
                column.append(head_colour)
            elif distance < 3.5:
                column.append(_scale(body, (3.5 - distance) / 2.5 * 0.85))
            else:
                column.append(_scale(body, 0.04))
        frame.append(column)
    return frame


def cylon(t, sticks, leds, colours):
    """One scanner eye sweeping the whole kit and bouncing back."""
    eye, halo = _c(colours, 0, CRIMSON), _c(colours, 1, WHITE)
    frame = _blank(sticks, leds, 0.03, eye)
    span = sticks * leds
    raw = t * 7
    head = int(raw % (2 * span))
    head = head if head < span else 2 * span - head
    for offset in range(-3, 4):
        index = head + offset
        if 0 <= index < span:
            x, y = divmod(index, leds)
            level = (1.0 - abs(offset) / 4.0) ** 2
            frame[x][y] = _scale(_mix(eye, halo, level ** 3), level)
    return frame


def pingpong(t, sticks, leds, colours):
    """A bright pulse bouncing up and down every stick."""
    core, glow = _c(colours, 0, LIME), _c(colours, 1, GREEN)
    frame = _blank(sticks, leds, 0.03)
    span = leds * 2 - 2
    raw = (t * 9) % span
    position = raw if raw < leds else span - raw
    for stick in range(sticks):
        for led in range(leds):
            distance = abs(led - position)
            if distance < 1.2:
                frame[stick][led] = _scale(core, 1.0 - distance / 1.2)
            elif distance < 2.4:
                frame[stick][led] = _scale(glow, 0.35 * (1.0 - (distance - 1.2) / 1.2))
    return frame


def ladder(t, sticks, leds, colours):
    """A stepped chaser climbing a rung every beat."""
    first, second = _c(colours, 0, GREEN), _c(colours, 1, CRIMSON)
    frame = _blank(sticks, leds, 0.02)
    step = int(t * 4) % (leds + sticks)
    for index in range(sticks):
        led = step - index
        if 0 <= led < leds:
            frame[index][led] = first if index % 2 == 0 else second
    return frame


def helix(t, sticks, leds, colours):
    """Two strands twisting around each other down the kit."""
    first, second = _c(colours, 0, GREEN), _c(colours, 1, CRIMSON)
    frame = []
    for stick in range(sticks):
        column = []
        for led in range(leds):
            angle = t * 2.0 + stick * 0.9
            level_a = max(0.0, math.sin(angle + led * 0.8)) ** 3
            level_b = max(0.0, math.sin(angle + led * 0.8 + math.pi)) ** 3
            column.append(_mix(_scale(first, level_a), _scale(second, level_b), level_b))
        frame.append(column)
    return frame


def spiral(t, sticks, leds, colours):
    """A rotating band of colour across the grid."""
    first, second = _c(colours, 0, GREEN), _c(colours, 1, CRIMSON)
    frame = []
    for stick in range(sticks):
        column = []
        for led in range(leds):
            angle = math.atan2(led - (leds - 1) / 2, stick - (sticks - 1) / 2)
            radius = math.hypot(led - (leds - 1) / 2, stick - (sticks - 1) / 2)
            wave = 0.5 + 0.5 * math.sin(angle * 3 + radius * 1.4 - t * 3.0)
            column.append(_scale(_mix(first, second, wave), 0.15 + 0.85 * wave ** 2))
        frame.append(column)
    return frame


def moire(t, sticks, leds, colours):
    """Two grids interfering; the pattern drifts and breathes."""
    first, second = _c(colours, 0, ICE), _c(colours, 1, CRIMSON)
    frame = []
    for stick in range(sticks):
        column = []
        for led in range(leds):
            first_wave = math.sin((stick + led) * 0.9 + t * 1.4)
            second_wave = math.sin((stick - led) * 0.75 - t * 1.1)
            value = (first_wave + second_wave) / 2
            column.append(_scale(first if value > 0 else second, abs(value) ** 1.5))
        frame.append(column)
    return frame


def ripple(t, sticks, leds, colours):
    """Rings spreading from the middle of the kit."""
    first, second = _c(colours, 0, GREEN), _c(colours, 1, CRIMSON)
    centre_x, centre_y = (sticks - 1) / 2, (leds - 1) / 2
    frame = []
    for stick in range(sticks):
        column = []
        for led in range(leds):
            distance = math.hypot(stick - centre_x, led - centre_y)
            wave = math.sin(distance * 1.8 - t * 4.0)
            column.append(_scale(_mix(first, second, distance / max(sticks, leds)),
                                 max(0.0, wave) ** 3))
        frame.append(column)
    return frame


def duel(t, sticks, leds, colours):
    """Two colours circling each other, swapping sides."""
    first, second = _c(colours, 0, CRIMSON), _c(colours, 1, GREEN)
    frame = []
    swing = 0.5 + 0.5 * math.sin(t * 0.55)
    for stick in range(sticks):
        side = stick / max(sticks - 1, 1)
        closeness = abs(side - swing)
        colour = _mix(first, second, min(1.0, closeness * 2.0))
        glow = 0.35 + 0.65 * (1.0 - closeness)
        frame.append([_scale(colour, glow * (0.75 + 0.25 * math.sin(t * 2.0 + stick)))
                      for _ in range(leds)])
    return frame


def crossfade(t, sticks, leds, colours):
    """The whole kit fading between two colours, stick by stick."""
    first, second = _c(colours, 0, GREEN), _c(colours, 1, CRIMSON)
    frame = []
    for stick in range(sticks):
        wave = 0.5 + 0.5 * math.sin(t * 1.2 - stick * 0.5)
        frame.append([_scale(_mix(first, second, wave), 0.35 + 0.65 * wave) for _ in range(leds)])
    return frame


def slots(t, sticks, leds, colours):
    """Rolling stripes that slow down and stop on a colour."""
    first, second = _c(colours, 0, CRIMSON), _c(colours, 1, GREEN)
    frame = []
    period = 3.0
    cycle = int(t / period)
    progress = (t % period) / period
    speed = (1.0 - progress) ** 2 * 10 + 0.4
    offset = int((t - cycle * period) * speed)
    for stick in range(sticks):
        column = []
        for led in range(leds):
            stripe = (led + offset + stick * 2) % 4
            column.append(_scale(first if stripe < 2 else second, 0.9 if stripe < 2 else 0.55))
        frame.append(column)
    return frame


# ------------------------------------------------------------------ games
def snake(t, sticks, leds, colours):
    """An auto-playing snake zig-zagging across the 8x8 grid."""
    body, apple = _c(colours, 0, GREEN), _c(colours, 1, CRIMSON)
    frame = _blank(sticks, leds, 0.02)
    step = int(t * 6)
    length = 7
    for index in range(length):
        move = step - index
        row = move // sticks
        column_index = move % sticks
        x = column_index if row % 2 == 1 else sticks - 1 - column_index
        y = row % leds
        if 0 <= x < sticks:
            level = 1.0 if index == 0 else 1.0 - index / (length + 1)
            frame[x][y] = _scale(WHITE if index == 0 else body, level)
    frame[(step // 3) % sticks][(step // 5) % leds] = apple
    return frame


def tetris(t, sticks, leds, colours):
    """One falling tetromino, rotating as the floor comes up."""
    first, second = _c(colours, 0, GREEN), _c(colours, 1, CRIMSON)
    frame = _blank(sticks, leds, 0.02)
    fall = int(t * 3) % (leds + 3)
    shape = int(t / 4) % 4
    blocks = {
        0: ((0, 0), (1, 0), (0, 1), (1, 1)),
        1: ((0, 0), (1, 0), (2, 0), (3, 0)),
        2: ((0, 0), (1, 0), (1, 1), (2, 1)),
        3: ((0, 0), (0, 1), (1, 1), (1, 2)),
    }[shape]
    offset_x = (sticks - 3) // 2
    for dx, dy in blocks:
        x = offset_x + dx
        y = leds - 1 - (fall - dy)
        if 0 <= x < sticks and 0 <= y < leds:
            frame[x][y] = first if shape % 2 else second
    return frame


def invaders(t, sticks, leds, colours):
    """A little marching formation stepping side to side."""
    alien, shot = _c(colours, 0, GREEN), _c(colours, 1, CRIMSON)
    frame = _blank(sticks, leds, 0.02, alien)
    march = int(t * 3) % 4
    shift = [0, 1, 0, -1][march]
    for row in range(2):
        for column_index in range(3):
            x = 1 + column_index * 2 + shift
            y = leds - 1 - row * 2 - 1
            if 0 <= x < sticks:
                frame[x][y] = WHITE if (row + column_index) % 2 else alien
    for index in range(2):
        shot_y = (int(t * 7) + index * 3) % leds
        frame[4][shot_y] = shot
    return frame


def pong(t, sticks, leds, colours):
    """A ball bouncing between two paddles, both of them missable."""
    left, right, ball = (_c(colours, 0, GREEN), _c(colours, 1, CRIMSON),
                         _c(colours, 2, WHITE))
    frame = _blank(sticks, leds, 0.02)
    x = int((0.5 + 0.5 * math.sin(t * 1.8)) * (sticks - 1))
    y = int((0.5 + 0.5 * math.sin(t * 2.7)) * (leds - 1))
    frame[0][int((0.5 + 0.5 * math.sin(t * 1.3)) * (leds - 1))] = left
    frame[sticks - 1][int((0.5 + 0.5 * math.cos(t * 1.7)) * (leds - 1))] = right
    frame[x][y] = ball
    return frame


# ------------------------------------------------------------------ real data
def _read_load():
    with open("/proc/loadavg") as handle:
        return float(handle.read().split()[0])


def _read_temp():
    import glob
    values = []
    for path in glob.glob("/sys/class/hwmon/hwmon*/temp1_input"):
        try:
            with open(path) as handle:
                values.append(int(handle.read()) / 1000.0)
        except OSError:
            pass
    return max(values) if values else 40.0


def _read_memory():
    with open("/proc/meminfo") as handle:
        lines = handle.read().splitlines()
    total = available = 0
    for line in lines:
        if line.startswith("MemTotal:"):
            total = int(line.split()[1])
        elif line.startswith("MemAvailable:"):
            available = int(line.split()[1])
    return 0.0 if not total else (1.0 - available / total) * 100


def _read_network():
    import glob
    total = 0
    for path in glob.glob("/sys/class/net/*/statistics/tx_bytes"):
        if "/lo/" in path:
            continue
        try:
            with open(path) as handle:
                total += int(handle.read())
        except OSError:
            pass
    return total


def _read_disk():
    total = 0
    with open("/proc/diskstats") as handle:
        for line in handle:
            parts = line.split()
            if len(parts) > 9 and parts[2].startswith(("sd", "nvme", "dm-")):
                total += int(parts[9])
    return total


def _bar(frame, sticks, leds, fraction, colour):
    lit = fraction * sticks * leds
    for index in range(sticks * leds):
        stick, led = divmod(index, leds)
        level = max(0.0, min(1.0, lit - index))
        if level > 0:
            frame[stick][led] = _scale(colour, 0.35 + 0.65 * level)


def cpu_load(t, sticks, leds, colours):
    """Real load average as a filling bar, low colour to high colour."""
    low, high = _c(colours, 0, GREEN), _c(colours, 1, CRIMSON)
    fraction = max(0.0, min(1.0, _cached("load", 0.5, _read_load) / 8.0))
    frame = _blank(sticks, leds, 0.02)
    _bar(frame, sticks, leds, fraction, _mix(low, high, fraction))
    return frame


def cpu_temp(t, sticks, leds, colours):
    """Real package temperature, 30 C to 90 C across the kit."""
    cool, hot = _c(colours, 0, ICE), _c(colours, 1, CRIMSON)
    fraction = max(0.0, min(1.0, (_cached("temp", 1.0, _read_temp) - 30) / 60))
    frame = _blank(sticks, leds, 0.02)
    _bar(frame, sticks, leds, fraction, _mix(cool, hot, fraction))
    return frame


def memory(t, sticks, leds, colours):
    """Real memory use as a bar."""
    low, high = _c(colours, 0, GREEN), _c(colours, 1, VIOLET)
    fraction = max(0.0, min(1.0, _cached("mem", 2.0, _read_memory) / 100))
    frame = _blank(sticks, leds, 0.02)
    _bar(frame, sticks, leds, fraction, _mix(low, high, fraction))
    return frame


def binary_clock(t, sticks, leds, colours):
    """The real time in binary, one column per digit."""
    even, odd = _c(colours, 0, GREEN), _c(colours, 1, CRIMSON)
    now = time.localtime()
    digits = [now.tm_hour // 10, now.tm_hour % 10, now.tm_min // 10, now.tm_min % 10,
              now.tm_sec // 10, now.tm_sec % 10]
    frame = _blank(sticks, leds, 0.02)
    for index, digit in enumerate(digits[:sticks]):
        for bit in range(min(4, leds)):
            if digit >> bit & 1:
                frame[index][leds - 1 - bit] = even if index % 2 == 0 else odd
    return frame


def network(t, sticks, leds, colours):
    """Real transmit rate, scaled so idle is dim and a big transfer fills it."""
    colour = _c(colours, 0, ICE)
    current = _cached("net", 0.25, _read_network)
    previous = _LAST.get("net")
    _LAST["net"] = current
    rate = 0.0 if previous is None else max(0.0, (current - previous) / 0.25)
    frame = _blank(sticks, leds, 0.02)
    _bar(frame, sticks, leds, min(1.0, rate / (40 * 1024 * 1024)), colour)
    return frame


def disk_activity(t, sticks, leds, colours):
    """Real disk sector traffic, flashing bright while it works."""
    base, spark = _c(colours, 0, AMBER), _c(colours, 1, WHITE)
    current = _cached("disk", 0.25, _read_disk)
    previous = _LAST.get("disk")
    _LAST["disk"] = current
    rate = 0.0 if previous is None else max(0.0, (current - previous) / 0.25)
    fraction = min(1.0, rate / 20000)
    frame = _blank(sticks, leds, 0.02)
    _bar(frame, sticks, leds, fraction, base)
    if fraction > 0.05:
        tick = int(t * 12)
        for index in range(int(fraction * sticks * leds)):
            stick, led = divmod(index, leds)
            frame[stick][led] = _scale(spark, 0.25 + 0.75 * _hash(tick, index))
    return frame


# name, function, palette slots (defaults), slot labels
SPECS = [
    ("Binary Rain", binary_rain, [GREEN, WHITE], ["Trail", "Head"]),
    ("Embers", embers, [WHITE, CRIMSON], ["Sparks", "Embers"]),
    ("Aurora", aurora, [GREEN, VIOLET], ["First", "Second"]),
    ("Lightning", lightning, [WHITE], ["Bolt"]),
    ("Candle", candle, [AMBER], ["Flame"]),
    ("Tide", tide, [GREEN, CRIMSON], ["Trough", "Crest"]),
    ("Snowfall", snowfall, [WHITE, ICE], ["Flake", "Tail"]),
    ("Starfield", starfield, [WHITE, ICE], ["Bright", "Dim"]),
    ("Fireflies", fireflies, [LIME], ["Glow"]),
    ("Fog", fog, [GREEN], ["Haze"]),
    ("Heartbeat", heartbeat, [CRIMSON], ["Pulse"]),
    ("Serpent", serpent, [GREEN, CRIMSON], ["Body", "Head"]),
    ("Cylon", cylon, [CRIMSON, WHITE], ["Eye", "Halo"]),
    ("Ping Pong", pingpong, [LIME, GREEN], ["Core", "Glow"]),
    ("Ladder", ladder, [GREEN, CRIMSON], ["First", "Second"]),
    ("Helix", helix, [GREEN, CRIMSON], ["Strand A", "Strand B"]),
    ("Spiral", spiral, [GREEN, CRIMSON], ["First", "Second"]),
    ("Moire", moire, [ICE, CRIMSON], ["Light", "Dark"]),
    ("Ripple", ripple, [GREEN, CRIMSON], ["Near", "Far"]),
    ("Duel", duel, [CRIMSON, GREEN], ["First", "Second"]),
    ("Crossfade", crossfade, [GREEN, CRIMSON], ["First", "Second"]),
    ("Slot Machine", slots, [CRIMSON, GREEN], ["First", "Second"]),
    ("Snake", snake, [GREEN, CRIMSON], ["Snake", "Apple"]),
    ("Tetris", tetris, [GREEN, CRIMSON], ["Piece A", "Piece B"]),
    ("Invaders", invaders, [GREEN, CRIMSON], ["Aliens", "Shots"]),
    ("Pong", pong, [GREEN, CRIMSON, WHITE], ["Left", "Right", "Ball"]),
    ("CPU Load", cpu_load, [GREEN, CRIMSON], ["Idle", "Loaded"]),
    ("CPU Temp", cpu_temp, [ICE, CRIMSON], ["Cool", "Hot"]),
    ("Memory", memory, [GREEN, VIOLET], ["Low", "High"]),
    ("Binary Clock", binary_clock, [GREEN, CRIMSON], ["Even", "Odd"]),
    ("Network", network, [ICE], ["Traffic"]),
    ("Disk Activity", disk_activity, [AMBER, WHITE], ["Work", "Spark"]),
]

EFFECT_NAMES = [name for name, _fn, _palette, _labels in SPECS]
BY_NAME = {name: (fn, palette, labels) for name, fn, palette, labels in SPECS}
