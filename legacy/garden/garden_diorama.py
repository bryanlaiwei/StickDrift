"""Fixed-camera 3D art layered over the existing garden interaction model."""
import math

import pygame

from garden_3d import assets
from garden_story import StoryGame, GOLD


class DioramaGame(StoryGame):
    def __init__(self, args):
        self.art = assets()
        self.scaled_art = {}
        super().__init__(args)
        self.meta["renderer"] = "orthographic-3d-baked-sprites-v1"

    def sprite(self, key, size):
        size = tuple(max(1, int(n)) for n in size)
        cache_key = (key, size)
        if cache_key not in self.scaled_art:
            self.scaled_art[cache_key] = pygame.transform.smoothscale(self.art[key], size)
        return self.scaled_art[cache_key]

    def cottage(self, surface):
        surface.blit(self.art["cottage"], (855, 187))

    def mabel(self, x, y, scale=1):
        height = int(255 * scale)
        img = self.sprite("mabel", (height * 320 / 510, height))
        pygame.draw.ellipse(self.screen, (85, 117, 87), (x - 51 * scale, y - 15 * scale, 102 * scale, 21 * scale))
        self.screen.blit(img, (int(x - img.get_width() / 2), int(y - height)))

    def tree(self, cx, cy):
        pygame.draw.ellipse(self.screen, (82, 119, 85), (cx - 188, cy + 166, 376, 53))
        self.screen.blit(self.art["tree"], (cx - 265, cy - 245))

    def bird(self, pos, hand, scale=1, flying=True):
        x, y = pos
        frame = int(self.anim_time() * 6) % 3 if flying else 1
        img = self.sprite(f"{hand}{frame}", (82 * scale, 67 * scale))
        pygame.draw.ellipse(self.screen, (83, 115, 87), (x - 22 * scale, y + 29 * scale, 44 * scale, 9 * scale))
        self.screen.blit(img, (int(x - img.get_width() / 2), int(y - img.get_height() / 2)))

    def apple_at(self, x, y, scale=1):
        img = self.sprite("apple", (64 * scale, 69 * scale))
        self.screen.blit(img, (int(x - img.get_width() / 2), int(y - img.get_height() / 2)))

    def flower_at(self, x, y, scale):
        img = self.sprite("flower", (40 * scale, 50 * scale))
        self.screen.blit(img, (int(x - img.get_width() / 2), int(y - img.get_height() * 0.4)))

    def draw_butterfly(self, hand, p, sparkle):
        x, y = self.px(hand, p)
        # Rounded, layered wings match the dimensional bird palette.
        flap = 0.7 + 0.3 * abs(math.sin(self.anim_time() * 7))
        for sign in (-1, 1):
            width = int(28 * flap)
            rect = pygame.Rect(x if sign > 0 else x - width, y - 23, width, 29)
            pygame.draw.ellipse(self.screen, (169, 100, 54), rect.move(0, 3))
            pygame.draw.ellipse(self.screen, (237, 170, 79), rect)
            pygame.draw.ellipse(self.screen, (255, 210, 129), rect.inflate(-9, -10).move(0, -3))
            pygame.draw.ellipse(self.screen, (231, 191, 113), (x if sign > 0 else x - width + 3, y + 1, width - 3, 20))
        pygame.draw.ellipse(self.screen, (94, 80, 55), (x - 3, y - 18, 6, 38))
        if sparkle:
            for i in range(5):
                a = self.anim_time() + i * math.tau / 5
                pygame.draw.circle(self.screen, GOLD, (int(x + 40 * math.cos(a)), int(y + 40 * math.sin(a))), 3)
