#!/usr/bin/env python3
"""Effects for the K70, written for a keyboard rather than a grid.

The board has 142 colour slots of which 114 answer to colour; they run in HID
usage order (A, B, C ... then the special keys), so an effect here thinks in
"position along the board" instead of rows and columns.

Each effect: fn(t, count, colours) -> list of (r, g, b), one per paintable slot.
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
        speed = 2.0 + _hash(index, 5) * 3.0
        level, colour = 0.0, trail
        for drop in range(2):
            position = (t * speed + _hash(index, drop) * count + drop * count / 3) % count
            distance = abs(position - index)
            distance = min(distance, count - distance)
            if distance < 1.5:
                level, colour = 1.0, head
            elif distance < 6:
                fade = (6 - distance) / 4.5
                if fade > level:
                    level, colour = fade * 0.8, trail
        frame.append(_scale(colour, level))
    return frame


def wave(t, count, colours):
    first, second = _c(colours, 0, GREEN), _c(colours, 1, CRIMSON)
    frame = []
    for index in range(count):
        phase = t * 2.2 - index * 0.12
        wave_value = 0.5 + 0.5 * math.sin(phase)
        frame.append(_scale(_mix(first, second, wave_value), 0.15 + 0.85 * wave_value ** 1.6))
    return frame


def comet(t, count, colours):
    body, head = _c(colours, 0, GREEN), _c(colours, 1, WHITE)
    head_position = (t * 18) % count
    frame = []
    for index in range(count):
        distance = (head_position - index) % count
        if distance < 1.0:
            frame.append(head)
        elif distance < 12:
            frame.append(_scale(body, (12 - distance) / 11 * 0.9))
        else:
            frame.append(_scale(body, 0.03))
    return frame


def breathing(t, count, colours):
    colour = _c(colours, 0, CRIMSON)
    level = 0.25 + 0.75 * (0.5 + 0.5 * math.sin(t * 1.6 - math.pi / 2)) ** 1.5
    return [_scale(colour, level) for _ in range(count)]


def sparkle(t, count, colours):
    first, second = _c(colours, 0, WHITE), _c(colours, 1, GREEN)
    tick = int(t * 10)
    frame = []
    for index in range(count):
        level, colour = 0.02, first
        for seed in (0, 1):
            if _hash(index, seed, tick // 2) > 0.972:
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
        wave_value = math.sin(distance * 0.45 - t * 4.0)
        frame.append(_scale(_mix(first, second, distance / count), max(0.0, wave_value) ** 3))
    return frame


def chase(t, count, colours):
    first, second = _c(colours, 0, GREEN), _c(colours, 1, CRIMSON)
    frame = []
    step = int(t * 14) % 4
    for index in range(count):
        frame.append(first if (index + step) % 4 < 2 else second)
    return frame


def clap(t, count, colours):
    """A short flare that sweeps out from the middle, like an applause ripple."""
    colour = _c(colours, 0, AMBER)
    centre = (count - 1) / 2
    frame = []
    for index in range(count):
        distance = abs(index - centre) / centre
        pulse = math.sin((t * 3.0 - distance) * math.pi)
        frame.append(_scale(colour, max(0.0, pulse) ** 2))
    return frame


SPECS = [
    ("KB Rain", rain, [GREEN, WHITE], ["Trail", "Head"]),
    ("KB Wave", wave, [GREEN, CRIMSON], ["First", "Second"]),
    ("KB Comet", comet, [GREEN, WHITE], ["Body", "Head"]),
    ("KB Breathing", breathing, [CRIMSON], ["Colour"]),
    ("KB Sparkle", sparkle, [WHITE, GREEN], ["Spark", "Glow"]),
    ("KB Ripple", ripple, [GREEN, CRIMSON], ["Near", "Far"]),
    ("KB Chase", chase, [GREEN, CRIMSON], ["First", "Second"]),
    ("KB Applause", clap, [AMBER], ["Colour"]),
]

EFFECT_NAMES = [name for name, _fn, _palette, _labels in SPECS]
BY_NAME = {name: (fn, palette, labels) for name, fn, palette, labels in SPECS}
