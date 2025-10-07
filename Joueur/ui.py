import pygame
from pygame.locals import *


def wrap_text(text, font, max_width):
    words = text.split()
    lines = []
    if not words:
        return lines
    cur = words[0]
    for w in words[1:]:
        test = cur + ' ' + w
        if font.size(test)[0] <= max_width:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def init_ui(capteur, nb_rounds):
    """Initialise pygame et les ressources graphiques pour l'instance Capteur."""
    pygame.init()
    capteur.screen = pygame.display.set_mode((1200, 800))
    pygame.display.set_caption(f"Capteur {capteur.id}")
    capteur.font_big = pygame.font.Font(None, 60)
    capteur.font_medium = pygame.font.Font(None, 40)
    capteur.font_small = pygame.font.Font(None, 24)

    # Charger avatars si possible
    for idx, fname in enumerate(capteur.avatar_filenames):
        if capteur.avatar_images[idx] is not None:
            continue
        try:
            capteur.avatar_images[idx] = pygame.image.load(fname)
        except Exception:
            surf = pygame.Surface((100, 100))
            surf.fill((80 + (idx * 40) % 175, 80, 120))
            capteur.avatar_images[idx] = surf


def draw_frame(capteur, nb_rounds):
    """Dessine une frame complète pour l'instance Capteur."""
    if not capteur.screen:
        return

    # choix de fonds selon rôle
    if capteur.role == "espion":
        bg, accent = (40, 10, 10), (255, 80, 80)
    elif capteur.role:
        bg, accent = (10, 40, 10), (80, 255, 80)
    else:
        bg, accent = (10, 10, 40), (80, 80, 255)

    capteur.screen.fill(bg)

    for sx, sy in capteur.stars:
        pygame.draw.circle(capteur.screen, (255, 255, 255), (sx, sy), 1)

    # petits helpers locaux
    def draw_text(text, x, y, color=(255, 255, 255), font=None):
        if not font:
            font = capteur.font_medium
        text_surf = font.render(text, True, color)
        capteur.screen.blit(text_surf, (x, y))

    # dessine avatars et informations
    all_capteurs = sorted(list(capteur.all_capteurs) + [capteur.id])
    num = len(all_capteurs)
    screen_w = capteur.screen.get_width()
    spacing = screen_w // max(num, 1)
    max_w = max(60, spacing - 60)

    x = (screen_w - num * spacing) // 2 + (spacing - max_w) // 2
    y = 200

    for cid in all_capteurs:
        # draw avatar
        index = capteur.assign_avatar_index(cid)
        avatar = capteur.avatar_images[index]
        desired_w = max(40, min(max_w, 200))
        cache_key = (index, desired_w)
        if cache_key not in capteur.scaled_avatars:
            scale = desired_w / avatar.get_width()
            desired_h = int(avatar.get_height() * scale)
            capteur.scaled_avatars[cache_key] = pygame.transform.smoothscale(avatar, (int(desired_w), desired_h))
        scaled = capteur.scaled_avatars[cache_key]
        rect = scaled.get_rect(x=x, y=y)
        capteur.screen.blit(scaled, rect)

        id_surf = capteur.font_small.render(cid, True, (255, 255, 255))
        capteur.screen.blit(id_surf, (x + (rect.width - id_surf.get_width()) // 2, y + rect.height + 6))

        is_spy = capteur.results and capteur.results.get('espion') == cid
        is_accused = capteur.results and capteur.results.get('accuse') == cid
        if is_spy:
            spy_surf = capteur.font_small.render("IMP", True, (255, 0, 0))
            capteur.screen.blit(spy_surf, (x + (rect.width - spy_surf.get_width()) // 2, y - 20))
        if is_accused:
            pygame.draw.line(capteur.screen, (255, 0, 0), (x, y), (x + rect.width, y + rect.height), 4)
            pygame.draw.line(capteur.screen, (255, 0, 0), (x + rect.width, y), (x, y + rect.height), 4)

        temps = capteur.mes_temperatures if cid == capteur.id else capteur.temperatures.get(cid, [])
        temp_y = y + rect.height + 30
        for r in range(nb_rounds):
            temp_str = f"R{r+1}: {temps[r] if r < len(temps) else '--'}"
            color = (200, 200, 200) if r < len(temps) else (100, 100, 100)
            text_surf = capteur.font_small.render(temp_str, True, color)
            capteur.screen.blit(text_surf, (x + (rect.width - text_surf.get_width()) // 2, temp_y))
            temp_y += 22

        if capteur.results and cid in capteur.results.get('votes', {}):
            vote_surf = capteur.font_small.render(f"V1: {capteur.results['votes'][cid]}", True, (255, 200, 0))
            capteur.screen.blit(vote_surf, (x + (rect.width - vote_surf.get_width()) // 2, temp_y + 8))

        if capteur.results and cid in capteur.results.get('votes_round2', {}):
            vote_surf = capteur.font_small.render(f"V2: {capteur.results['votes_round2'][cid]}", True, (255, 200, 0))
            capteur.screen.blit(vote_surf, (x + (rect.width - vote_surf.get_width()) // 2, temp_y + 28))

        # afficher défense si présente
        if capteur.defense_recue and capteur.defense_recue.get('capteur_id') == cid:
            defense_text = capteur.defense_recue.get('defense', '')
            if defense_text:
                max_text_w = rect.width
                lines = wrap_text(defense_text, capteur.font_small, max_text_w)
                box_h = len(lines) * (capteur.font_small.get_linesize() - 4) + 8
                box_x = x
                box_y = temp_y + 60
                s = pygame.Surface((max_text_w + 8, box_h), pygame.SRCALPHA)
                s.fill((0, 0, 0, 150))
                capteur.screen.blit(s, (box_x - 4, box_y))
                ly = box_y + 4
                for line in lines:
                    txt = capteur.font_small.render(line, True, (255, 255, 255))
                    capteur.screen.blit(txt, (box_x, ly))
                    ly += capteur.font_small.get_linesize() - 4

        x += spacing

    # Dessiner les éléments UI supérieurs
    def draw_main_ui():
        draw_text = lambda t, X, Y, c=(255,255,255), f=None: capteur.screen.blit((f or capteur.font_medium).render(t, True, c), (X,Y))
        # titre
        if capteur.role == "espion":
            accent = (255,80,80)
        elif capteur.role:
            accent = (80,255,80)
        else:
            accent = (80,80,255)
        draw_text("Jeu raspberry", 400, 20, accent, capteur.font_big)
        role_text = "IMPOSTOR" if capteur.role == "espion" else "CREWMATE" if capteur.role else "WAITING FOR ROLE"
        draw_text(f"You are the {role_text}", 20, 80, accent, capteur.font_medium)
        draw_text(f"Round: {capteur.round_count}/{nb_rounds}", 20, 130, (255,255,255), capteur.font_medium)
        draw_text(f"Current City: {capteur.ville or 'None'}", 20, 160, (255,255,255), capteur.font_medium)
        draw_text("Crew:", 20, 190, accent, capteur.font_medium)

    draw_main_ui()

    # panneaux de résultats si exists
    if capteur.results:
        panel = pygame.Surface((700, 400), pygame.SRCALPHA)
        panel.fill((0,0,0,150))
        capteur.screen.blit(panel, (250,80))
        if capteur.id == capteur.results.get('espion'):
            if capteur.results.get('gagnant') == "ESPION":
                msg = "You won as Impostor!"
                color = (255,80,80)
            else:
                msg = "You were caught!"
                color = (255,100,100)
        else:
            if capteur.results.get('gagnant') == "CAPTEURS":
                msg = "Crew Wins!"
                color = (80,255,80)
            else:
                msg = "Impostor Wins!"
                color = (255,80,80)
        capteur.screen.blit(capteur.font_medium.render(msg, True, color), (450,150))
        capteur.screen.blit(capteur.font_small.render(f"Accused R1: {capteur.results.get('accuse_round1','N/A')}", True, (255,255,255)), (450,200))
        capteur.screen.blit(capteur.font_small.render(f"Accused R2: {capteur.results.get('accuse')}", True, (255,255,255)), (450,230))
        capteur.screen.blit(capteur.font_small.render(f"Real Impostor: {capteur.results.get('espion')}", True, (255,255,255)), (450,260))
