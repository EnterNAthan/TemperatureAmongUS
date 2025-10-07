import pygame
import sys
from arbitreIA import ServeurArbitre
import threading
import queue
import math
import time
import random
import tkinter as tk
from tkinter import simpledialog
import os

class AmongUsPlayer:
    def __init__(self, color, x, y, scale=1.0):
        self.color = color
        self.x = x
        self.y = y
        self.scale = scale
        self.animation_offset = 0
        # Chargement de l'image
        image_path = f'among_{color}.png'
        try:
            self.image = pygame.image.load(image_path)
            self.image = pygame.transform.scale(self.image, (80, 80))
        except pygame.error:
            print(f"Erreur: Impossible de charger l'image {image_path}")
            self.image = None
        
    def draw(self, screen, is_spy=False, is_dead=False):
        if self.image:
            # Position avec animation
            y_pos = self.y + math.sin(self.animation_offset) * 3
            img_rect = self.image.get_rect(center=(self.x, y_pos))
            screen.blit(self.image, img_rect)
            
            if is_dead:
                # X rouge pour les joueurs éliminés
                pygame.draw.line(screen, (255, 0, 0), 
                               (self.x - 30, y_pos - 30), 
                               (self.x + 30, y_pos + 30), 4)
                pygame.draw.line(screen, (255, 0, 0), 
                               (self.x - 30, y_pos + 30), 
                               (self.x + 30, y_pos - 30), 4)

class ArbitreDisplay:
    def __init__(self, broker_ip):
        pygame.init()
        
        # Demande du nombre de joueurs
        root = tk.Tk()
        root.withdraw()
        nb_joueurs = simpledialog.askinteger("Configuration", 
                                           "Nombre de joueurs (2-10):", 
                                           minvalue=2, maxvalue=10)
        if nb_joueurs is None:
            sys.exit()

        # Configuration de la fenêtre
        self.WIDTH = 1280
        self.HEIGHT = 800
        self.screen = pygame.display.set_mode((self.WIDTH, self.HEIGHT))
        pygame.display.set_caption("Among Us - Serveur Arbitre")

        # Couleurs Among Us (correspondant aux noms des fichiers images)
        self.COLORS = ['red', 'blue', 'grn', 'yllw']  # Ajoutez les couleurs selon vos images

        # Configuration des sections
        self.sections = {
            'game': {'x': 20, 'y': 20, 'w': 300, 'h': 120},
            'players': {'x': 340, 'y': 20, 'w': 600, 'h': 400},
            'console': {'x': 20, 'y': 460, 'w': 920, 'h': 320},
            'votes': {'x': 960, 'y': 20, 'w': 300, 'h': 760}
        }
        
        # Étoiles pour le fond
        self.stars = [(random.randint(0, self.WIDTH), 
                      random.randint(0, self.HEIGHT), 
                      random.random()*2) for _ in range(100)]
        
        # Polices
        self.font_title = pygame.font.Font(None, 48)
        self.font_normal = pygame.font.Font(None, 32)
        self.font_small = pygame.font.Font(None, 24)
        
        # Variables du jeu
        self.player_objects = {}
        self.animation_time = 0
        self.message_queue = queue.Queue()
        self.console_messages = []
        self.max_console_lines = 15
        self.connected_players = {}
        self.current_round = 0
        self.spy = None
        self.votes = {}
        self.winner = None
        # IA dialog (captured from arbitreIA logs / Ollama responses)
        self.ai_avatar = None
        # try to load a dedicated IA avatar image (falls back to None)
        try:
            avatar_path = os.path.join(os.path.dirname(__file__), "among_ai.png")
            if os.path.exists(avatar_path):
                self.ai_avatar = pygame.image.load(avatar_path).convert_alpha()
                self.ai_avatar = pygame.transform.smoothscale(self.ai_avatar, (64, 64))
        except Exception:
            self.ai_avatar = None

        self.ai_dialogue = []
        self.max_ai_lines = 4
        
        # Démarrage du serveur
        self.serveur = ServeurArbitre(broker_ip, nb_joueurs)
        self.serveur.afficher = self.custom_print
        self.server_thread = threading.Thread(target=self.serveur.demarrer_serveur)
        self.server_thread.daemon = True
        self.server_thread.start()

        # Ajout d'un état pour la fin de partie
        self.game_over = False
        self.final_results = None  # Pour stocker les résultats finaux
        
        # Message d'aide pour les contrôles
        self.controls_text = "ECHAP: Quitter | R: Nouvelle partie"

        # Ajout des variables pour les fenêtres modales
        self.defense_modal = None
        self.analysis_modal = None
        self.modal_animation = 0
        self.modal_fade_in = 0
        
        # Police pour les modales
        self.font_defense = pygame.font.Font(None, 36)
        self.font_analysis = pygame.font.Font(None, 32)

    def draw_section(self, title, section, alpha=192):
        """Dessine une section avec fond semi-transparent"""
        section_surface = pygame.Surface((section['w'], section['h']), pygame.SRCALPHA)
        pygame.draw.rect(section_surface, (0, 0, 0, alpha), 
                        (0, 0, section['w'], section['h']))
        
        # Titre
        title_surface = self.font_title.render(title, True, (255, 255, 255))
        section_surface.blit(title_surface, (10, 10))
        
        self.screen.blit(section_surface, (section['x'], section['y']))
        return 50  # Retourne la hauteur après le titre

    def draw_console(self):
        """Dessine la console avec les messages"""
        y_offset = self.draw_section("Console", self.sections['console'])
        console_x = self.sections['console']['x']
        
        for message in self.console_messages[-self.max_console_lines:]:
            text_surface = self.font_small.render(message, True, (255, 255, 255))
            self.screen.blit(text_surface, 
                           (console_x + 10, 
                            self.sections['console']['y'] + y_offset))
            y_offset += 20

    def draw_space_background(self):
        """Dessine le fond spatial avec étoiles"""
        self.screen.fill((8, 8, 24))
        for x, y, size in self.stars:
            pygame.draw.circle(self.screen, (255, 255, 255), (int(x), int(y)), int(size))

    def create_player_positions(self):
        """Crée les positions des joueurs en cercle"""
        players = list(self.connected_players.keys())
        n = len(players)
        if n == 0:
            return

        section = self.sections['players']
        center_x = section['x'] + section['w'] // 2
        center_y = section['y'] + section['h'] // 2
        radius = min(section['w'], section['h']) * 0.35

        self.player_objects.clear()
        for i, player_id in enumerate(players):
            angle = (2 * math.pi * i / n) - math.pi/2
            x = center_x + radius * math.cos(angle)
            y = center_y + radius * math.sin(angle)
            color = self.COLORS[i % len(self.COLORS)]
            self.player_objects[player_id] = AmongUsPlayer(color, x, y)

    def draw_vote_info(self):
        """Affiche les informations de vote"""
        y_offset = self.draw_section("Votes", self.sections['votes'])
        votes_x = self.sections['votes']['x']
        
        for voter, voted_for in self.votes.items():
            text = f"{voter} → {voted_for}"
            text_surface = self.font_normal.render(text, True, (255, 255, 255))
            self.screen.blit(text_surface, 
                           (votes_x + 10, 
                            self.sections['votes']['y'] + y_offset))
            y_offset += 30

    def draw_game_status(self):
        """Affiche le statut du jeu"""
        y_offset = self.draw_section("État du Jeu", self.sections['game'])
        status_x = self.sections['game']['x']
        
        status_text = [
            f"Round: {self.current_round}/{self.serveur.nb_rounds}",
            f"Joueurs: {len(self.connected_players)}/{self.serveur.nb_joueurs}"
        ]
        
        for text in status_text:
            text_surface = self.font_normal.render(text, True, (255, 255, 255))
            self.screen.blit(text_surface, 
                           (status_x + 10, 
                            self.sections['game']['y'] + y_offset))
            y_offset += 30

    def custom_print(self, message):
        """Fonction d'affichage personnalisée pour le serveur"""
        self.message_queue.put(message)
        print(message)

    def draw_game_over(self):
        """Affiche l'écran de fin de partie"""
        if not self.game_over:
            return

        # Overlay semi-transparent
        overlay = pygame.Surface((self.WIDTH, self.HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 128))
        self.screen.blit(overlay, (0, 0))

        # Titre "Partie Terminée"
        title = self.font_title.render("Partie Terminée!", True, (255, 255, 255))
        title_rect = title.get_rect(center=(self.WIDTH // 2, 100))
        self.screen.blit(title, title_rect)

        # Résultats
        if hasattr(self.serveur, 'espion'):
            espion_text = f"L'espion était : {self.serveur.espion}"
            espion_surf = self.font_normal.render(espion_text, True, (255, 100, 100))
            self.screen.blit(espion_surf, (self.WIDTH // 2 - espion_surf.get_width() // 2, 160))

        # Contrôles
        controls = self.font_normal.render(self.controls_text, True, (200, 200, 200))
        controls_rect = controls.get_rect(center=(self.WIDTH // 2, self.HEIGHT - 40))
        self.screen.blit(controls, controls_rect)

    def handle_events(self):
        """Gère les événements clavier"""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
                
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    pygame.quit()
                    sys.exit()
                    
                elif event.key == pygame.K_r and self.game_over:
                    # Redémarrer une nouvelle partie
                    self.game_over = False
                    self.serveur.demarrer_jeu()

    def update_game_state(self):
        """Met à jour l'état du jeu depuis le serveur"""
        self.connected_players = self.serveur.capteurs_connectes
        self.current_round = self.serveur.round_actuel
        self.spy = self.serveur.espion
        
        # Détecter la fin de partie
        if not self.serveur.jeu_actif and self.current_round == 0 and self.spy is not None:
            self.game_over = True

        # Combine votes from arbitre IA: prefer second-round votes when available
        combined = {}
        if hasattr(self.serveur, 'votes_round1') and isinstance(self.serveur.votes_round1, dict):
            combined.update(self.serveur.votes_round1)
        if hasattr(self.serveur, 'votes_round2') and isinstance(self.serveur.votes_round2, dict):
            # round2 overrides round1 if same voter
            combined.update(self.serveur.votes_round2)
        self.votes = combined
        
        while not self.message_queue.empty():
            message = self.message_queue.get()
            self.console_messages.append(message)
            if len(self.console_messages) > self.max_console_lines:
                self.console_messages.pop(0)

            # Détecter la défense Ollama
            try:
                if "OLLAMA" in message and "Defense recuperee" in message:
                    parts = message.split(":", 2)
                    if len(parts) >= 3:
                        defense_text = parts[2].strip()
                        # Extraire l'ID du joueur qui se défend (à adapter selon le format du message)
                        player_id = message.split("[OLLAMA] Defense pour ")[1].split(":")[0]
                        self.defense_modal = DefenseModal(player_id, defense_text)
                        # L'analyse suivra après un délai
                        self.modal_fade_in = 0
                        threading.Timer(6.5, self.show_analysis_modal, args=[defense_text]).start()
            except Exception:
                pass

    def show_analysis_modal(self, defense_text):
        """Affiche la modale d'analyse après la défense"""
        analysis = f"Analyse de la défense : {defense_text}"  # À personnaliser
        self.analysis_modal = AnalysisModal(analysis)
        self.modal_fade_in = 0

    def draw_ai_panel(self):
        """Dessine un petit panneau IA (avatar + dialogue) en bas à droite"""
        box_w = 340
        box_h = 140
        margin = 16
        x = self.WIDTH - box_w - margin
        y = self.HEIGHT - box_h - margin

        # surface semi-transparente
        surf = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
        pygame.draw.rect(surf, (10, 12, 20, 220), (0, 0, box_w, box_h), border_radius=8)

        # avatar area
        avatar_x = 12
        avatar_y = 12
        if self.ai_avatar:
            surf.blit(self.ai_avatar, (avatar_x, avatar_y))
        else:
            # fallback: draw a small robot circle
            pygame.draw.circle(surf, (120, 180, 240), (avatar_x + 32, avatar_y + 32), 30)
            pygame.draw.circle(surf, (255, 255, 255), (avatar_x + 22, avatar_y + 24), 6)
            pygame.draw.circle(surf, (255, 255, 255), (avatar_x + 42, avatar_y + 24), 6)

        # Title
        title_surf = self.font_normal.render("Arbitre IA", True, (220, 220, 255))
        surf.blit(title_surf, (avatar_x + 72, avatar_y + 6))

        # Dialogue lines
        line_y = avatar_y + 40
        for i, line in enumerate(self.ai_dialogue[-self.max_ai_lines:]):
            # wrap long lines to fit roughly
            text = line
            text_surf = self.font_small.render(text, True, (235, 235, 235))
            surf.blit(text_surf, (avatar_x + 72, line_y + i * 24))

        # Blit panel to screen
        self.screen.blit(surf, (x, y))

    def run(self):
        """Boucle principale"""
        clock = pygame.time.Clock()
        
        while True:
            self.handle_events()  # Gestion des événements
            
            # Mise à jour de l'état
            self.update_game_state()
            if not self.player_objects or len(self.player_objects) != len(self.connected_players):
                self.create_player_positions()

            # Animation si le jeu n'est pas terminé
            if not self.game_over:
                self.animation_time += 0.05
                for player in self.player_objects.values():
                    player.animation_offset = self.animation_time

            # Dessin
            self.draw_space_background()
            self.draw_game_status()
            
            # Dessiner les joueurs
            for player_id, player in self.player_objects.items():
                is_spy = player_id == self.spy
                is_dead = False
                player.draw(self.screen, is_spy, is_dead)
                
                name_surface = self.font_small.render(str(player_id), True, (255, 255, 255))
                name_rect = name_surface.get_rect(center=(player.x, player.y + 50))
                self.screen.blit(name_surface, name_rect)

            self.draw_vote_info()
            self.draw_console()
            self.draw_ai_panel()

            # Afficher l'écran de fin si nécessaire
            if self.game_over:
                self.draw_game_over()

            # Gestion des modales
            if self.defense_modal:
                self.modal_fade_in = min(1.0, self.modal_fade_in + 0.05)
                self.defense_modal.draw(self.screen, self.WIDTH, self.HEIGHT, 
                                  self.modal_fade_in, self.font_defense)
                if self.defense_modal.should_close():
                    self.defense_modal = None
        
            elif self.analysis_modal:
                self.modal_fade_in = min(1.0, self.modal_fade_in + 0.05)
                self.analysis_modal.draw(self.screen, self.WIDTH, self.HEIGHT, 
                                   self.modal_fade_in, self.font_analysis)
                if self.analysis_modal.should_close():
                    self.analysis_modal = None

            pygame.display.flip()
            clock.tick(60)

class DefenseModal:
    def __init__(self, player_id, defense_text):
        self.player_id = player_id
        self.defense_text = defense_text
        self.creation_time = time.time()
        self.display_duration = 6.0  # Durée d'affichage en secondes
        
    def should_close(self):
        return time.time() - self.creation_time > self.display_duration
        
    def draw(self, screen, width, height, alpha, font_defense):
        # Fond semi-transparent noir
        overlay = pygame.Surface((width, height), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, int(128 * alpha)))
        screen.blit(overlay, (0, 0))
        
        # Fenêtre de défense
        modal_w, modal_h = 800, 300
        modal_x = (width - modal_w) // 2
        modal_y = (height - modal_h) // 2
        
        # Fond de la modale avec effet de brillance
        modal = pygame.Surface((modal_w, modal_h), pygame.SRCALPHA)
        pygame.draw.rect(modal, (30, 30, 50, int(230 * alpha)), 
                        (0, 0, modal_w, modal_h), border_radius=15)
        
        # Titre avec effet
        title = font_defense.render(f"Défense de {self.player_id}", True, (220, 220, 255))
        title_rect = title.get_rect(center=(modal_w//2, 50))
        modal.blit(title, title_rect)
        
        # Texte de défense
        words = self.defense_text.split()
        lines = []
        current_line = []
        
        for word in words:
            current_line.append(word)
            test_line = ' '.join(current_line)
            if font_defense.size(test_line)[0] > modal_w - 60:
                current_line.pop()
                lines.append(' '.join(current_line))
                current_line = [word]
        lines.append(' '.join(current_line))
        
        y = 100
        for line in lines:
            text = font_defense.render(line, True, (255, 255, 255))
            text_rect = text.get_rect(center=(modal_w//2, y))
            modal.blit(text, text_rect)
            y += 40
        
        screen.blit(modal, (modal_x, modal_y))

class AnalysisModal:
    def __init__(self, analysis_text):
        self.analysis_text = analysis_text
        self.creation_time = time.time()
        self.display_duration = 5.0
        
    def should_close(self):
        return time.time() - self.creation_time > self.display_duration
        
    def draw(self, screen, width, height, alpha, font_analysis):
        # Fond semi-transparent bleu foncé
        overlay = pygame.Surface((width, height), pygame.SRCALPHA)
        overlay.fill((0, 20, 40, int(128 * alpha)))
        screen.blit(overlay, (0, 0))
        
        # Fenêtre d'analyse
        modal_w, modal_h = 700, 250
        modal_x = (width - modal_w) // 2
        modal_y = (height - modal_h) // 2
        
        # Fond de la modale avec effet futuriste
        modal = pygame.Surface((modal_w, modal_h), pygame.SRCALPHA)
        pygame.draw.rect(modal, (20, 40, 80, int(230 * alpha)), 
                        (0, 0, modal_w, modal_h), border_radius=10)
        
        # Bordure lumineuse
        pygame.draw.rect(modal, (60, 130, 240, int(150 * alpha)), 
                        (0, 0, modal_w, modal_h), border_radius=10, width=2)
        
        # Titre
        title = font_analysis.render("Analyse IA", True, (100, 200, 255))
        title_rect = title.get_rect(center=(modal_w//2, 40))
        modal.blit(title, title_rect)
        
        # Texte d'analyse
        words = self.analysis_text.split()
        lines = []
        current_line = []
        
        for word in words:
            current_line.append(word)
            test_line = ' '.join(current_line)
            if font_analysis.size(test_line)[0] > modal_w - 60:
                current_line.pop()
                lines.append(' '.join(current_line))
                current_line = [word]
        lines.append(' '.join(current_line))
        
        y = 80
        for line in lines:
            text = font_analysis.render(line, True, (200, 230, 255))
            text_rect = text.get_rect(center=(modal_w//2, y))
            modal.blit(text, text_rect)
            y += 35
        
        screen.blit(modal, (modal_x, modal_y))


if __name__ == "__main__":
    import random
    IP_BROKER = "10.109.150.194"
    display = ArbitreDisplay(IP_BROKER)
    display.run()