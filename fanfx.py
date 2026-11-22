#!/usr/bin/env python3
"""My own effects for the board's ARGB headers.

Each header is treated as a 30-pixel strip; the same picture is drawn on both
so the case matches. An effect is a pure function of time:

    fn(t, count, colours) -> [(r, g, b), ...] of length count
"""
import math

GREEN = (0, 255, 65)
CRIMSON = (220, 20, 60)
WHITE = (255, 255, 255)
AMBER = (255, 165, 0)
ICE = (143, 214, 255)
VIOLET = (138, 43, 226)


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


def _scale(colour, amount):
    amount = max(0.0, min(1.0, amount))
    return tuple(int(channel * amount) for channel in colour)


def _mix(first, second, amount):
    amount = max(0.0, min(1.0, amount))
    return tuple(int(first[i] + (second[i] - first[i]) * amount) for i in range(3))


def rain(t, count, colours):
    trail, head = _c(colours, 0, GREEN), _c(colours, 1, WHITE)
    frame = []
    for index in range(count):
        speed = 6.0 + _hash(index, 4) * 4.0
        level, colour = 0.0, trail
        for drop in range(2):
            position = (t * speed + _hash(index, drop) * count + drop * count / 2) % count
            distance = abs(position - index)
            distance = min(distance, count - distance)
            if distance < 1.5:
                level, colour = 1.0, head
            elif distance < 7:
                fade = (7 - distance) / 5.5
                if fade > level:
                    level, colour = fade * 0.8, trail
        frame.append(_scale(colour, level))
    return frame


def wave(t, count, colours):
    first, second = _c(colours, 0, GREEN), _c(colours, 1, CRIMSON)
    frame = []
    for index in range(count):
        value = 0.5 + 0.5 * math.sin(t * 2.0 - index * 0.22)
        frame.append(_scale(_mix(first, second, value), 0.15 + 0.85 * value ** 1.5))
    return frame


def comet(t, count, colours):
    body, head = _c(colours, 0, GREEN), _c(colours, 1, WHITE)
    head_position = (t * 20) % count
    frame = []
    for index in range(count):
        distance = (head_position - index) % count
        if distance < 1.0:
            frame.append(head)
        elif distance < 14:
            frame.append(_scale(body, (14 - distance) / 13 * 0.9))
        else:
            frame.append(_scale(body, 0.03))
    return frame


def breathing(t, count, colours):
    colour = _c(colours, 0, CRIMSON)
    level = 0.2 + 0.8 * (0.5 + 0.5 * math.sin(t * 1.5 - math.pi / 2)) ** 1.5
    return [_scale(colour, level) for _ in range(count)]


def sparkle(t, count, colours):
    first, second = _c(colours, 0, WHITE), _c(colours, 1, GREEN)
    tick = int(t * 12)
    frame = []
    for index in range(count):
        level, colour = 0.02, first
        for seed in (0, 1):
            if _hash(index, seed, tick // 2) > 0.96:
                age = (tick % 2) / 2.0
                level, colour = (1.0 - age), (first if seed == 0 else second)
        frame.append(_scale(colour, level))
    return frame


def ripple(t, count, colours):
    first, second = _c(colours, 0, GREEN), _c(colours, 1, CRIMSON)
    centre = (count - 1) / 2
    frame = []
    for index in range(count):
        distance = abs(index - centre)
        value = math.sin(distance * 0.5 - t * 4.5)
        frame.append(_scale(_mix(first, second, distance / count), max(0.0, value) ** 3))
    return frame


def chase(t, count, colours):
    first, second = _c(colours, 0, GREEN), _c(colours, 1, CRIMSON)
    step = int(t * 16) % 6
    return [first if (index + step) % 6 < 3 else second for index in range(count)]


def tide(t, count, colours):
    first, second = _c(colours, 0, VIOLET), _c(colours, 1, ICE)
    frame = []
    for index in range(count):
        value = 0.5 + 0.5 * math.sin(t * 1.1 - index * 0.16)
        frame.append(_scale(_mix(first, second, value), 0.1 + 0.9 * value ** 2))
    return frame


def hearth(t, count, colours):
    """A slow low fire: ambers breathing, short sparks near the base."""
    ember, spark = _c(colours, 0, AMBER), _c(colours, 1, WHITE)
    frame = []
    tick = int(t * 10)
    for index in range(count):
        base = 0.12 + 0.10 * math.sin(t * 0.8 + index * 0.4)
        level = base * (1.0 - index / count * 0.4)
        colour = ember
        if _hash(index, tick // 2) > 0.985:
            level, colour = 0.9, spark
        frame.append(_scale(colour, level))
    return frame


def scanner(t, count, colours):
    eye, halo = _c(colours, 0, CRIMSON), _c(colours, 1, WHITE)
    span = count * 2 - 2
    raw = (t * 14) % span
    head = raw if raw < count else span - raw
    frame = []
    for index in range(count):
        distance = abs(index - head)
        if distance < 1.5:
            frame.append(_mix(eye, halo, 0.8))
        elif distance < 5:
            frame.append(_scale(eye, (5 - distance) / 4.5))
        else:
            frame.append(_scale(eye, 0.04))
    return frame


SPECS = [
    ("Fan Rain", rain, [GREEN, WHITE], ["Trail", "Head"]),
    ("Fan Wave", wave, [GREEN, CRIMSON], ["First", "Second"]),
    ("Fan Comet", comet, [GREEN, WHITE], ["Body", "Head"]),
    ("Fan Breathing", breathing, [CRIMSON], ["Colour"]),
    ("Fan Sparkle", sparkle, [WHITE, GREEN], ["Spark", "Glow"]),
    ("Fan Ripple", ripple, [GREEN, CRIMSON], ["Near", "Far"]),
    ("Fan Chase", chase, [GREEN, CRIMSON], ["First", "Second"]),
    ("Fan Tide", tide, [VIOLET, ICE], ["Deep", "Crest"]),
    ("Fan Hearth", hearth, [AMBER, WHITE], ["Ember", "Spark"]),
    ("Fan Scanner", scanner, [CRIMSON, WHITE], ["Eye", "Halo"]),
]

EFFECT_NAMES = [name for name, _fn, _palette, _labels in SPECS]
BY_NAME = {name: (fn, palette, labels) for name, fn, palette, labels in SPECS}
