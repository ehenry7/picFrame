import pygame

def draw_text_with_outline(screen, text, font, text_color, outline_color, pos, anchor="center"):
    """
    Draw text on a Pygame surface with an outline for improved readability.

    Args:
        screen (pygame.Surface): La surface sur laquelle dessiner.
        text (str): The text to display.
        font (pygame.font.Font): The font to use.
        text_color (tuple): La couleur du texte (R, G, B).
        outline_color (tuple): La couleur du contour (R, G, B).
        pos (tuple): La position (x, y) du texte.
        anchor (str): Le point d'ancrage pour la position ('center', 'topleft', etc.).
    """
    # Render the surfaces once.
    text_surface = font.render(text, True, text_color)
    outline_surface = font.render(text, True, outline_color)

    # Get the rectangle for positioning.
    text_rect = text_surface.get_rect(**{anchor: pos})
    
    # Draw the outline by offsetting the surface.
    offsets = [(-2, -2), (-2, 2), (2, -2), (2, 2)]
    for ox, oy in offsets:
        screen.blit(outline_surface, text_rect.move(ox, oy))
    
    # Draw the main text.
    screen.blit(text_surface, text_rect)