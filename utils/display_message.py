import pygame
import sys
import os
import glob
from platform_utils import IS_LINUX, get_pygame_display_flags, get_pygame_display_size

def draw_text(surface, text, font, color, center_pos):
    """Draw text centered at a given position."""
    text_surface = font.render(text, True, color)
    text_rect = text_surface.get_rect(center=center_pos)
    surface.blit(text_surface, text_rect)

def main():
    """Display a centered message on screen briefly."""
    if len(sys.argv) < 2:
        print("Usage: python display_message.py \"Your message\"")
        return

    message = sys.argv[1]

    # Ensure the display environment is configured correctly.
    if IS_LINUX and "SWAYSOCK" not in os.environ:
        user_id = os.getuid()
        sock_path_pattern = f"/run/user/{user_id}/sway-ipc.*"
        socks = glob.glob(sock_path_pattern)
        if socks:
            os.environ["SWAYSOCK"] = socks[0]

    pygame.init()

    screen = pygame.display.set_mode(get_pygame_display_size(), get_pygame_display_flags())
    screen.fill((0, 0, 0)) # Fond noir

    font = pygame.font.Font(None, 60) # Default font, size 60.
    draw_text(screen, message, font, (255, 255, 255), screen.get_rect().center)
    pygame.display.flip()

if __name__ == "__main__":
    main()