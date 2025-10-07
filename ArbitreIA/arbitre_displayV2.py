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
    def __init__(self, color, x, y):
        self.color = color
        self.x = x
        self.y = y
        self.animation_offset = 0
        try:
            self.image = pygame.image.load(f'among_{color}.png')
            self.image = pygame.transform.scale(self.image, (80, 80))
        except pygame.error:
            print(f"Erreur: Image among_{color}.png non trouvée")
            self.image = None

    def draw(self, screen, is_spy=False):
        if self.image:
            y_pos = self.y + math.sin(self.animation_offset) * 3
            screen.blit(self.image, self.image.get_rect(center=(self.x, y_pos)))
            if is_spy:
                pygame.draw.circle(screen, (255, 0, 0), (self.x, y_pos), 40, 2)

class ArbitreDisplay:
    def __init__(self, broker_ip):
        pygame.init()
        root = tk.Tk()
        root.withdraw()
        nb_joueurs = simpledialog.askinteger("Configuration", 
            "Nombre de joueurs (2-10):", minvalue=2, maxvalue=10)
        if nb_joueurs is None:
            sys.exit()

        # Configuration fenêtre et UI
        self.WIDTH, self.HEIGHT = 1280, 800
        self.screen = pygame.display.set_mode((self.WIDTH, self.HEIGHT))
        pygame.display.set_caption("Among Us - Serveur Arbitre")
        
        self.COLORS = ['red', 'blue', 'grn', 'yllw']
        self.font_normal = pygame.font.Font(None, 32)
        self.font_small = pygame.font.Font(None, 24)

        # Sections UI
        self.sections = {
            'game': {'x': 20, 'y': 20, 'w': 300, 'h': 120},
            'players': {'x': 340, 'y': 20, 'w': 600, 'h': 400},
            'console': {'x': 20, 'y': 460, 'w': 920, 'h': 320},
            'votes': {'x': 960, 'y': 20, 'w': 300, 'h': 760}
        }

        # État du jeu
        self.game_over = False
        self.player_objects = {}
        self.animation_time = 0
        self.message_queue = queue.Queue()
        self.console_messages = []
        self.connected_players = {}
        self.current_round = 0
        self.spy = None
        self.votes = {}
        
        # IA Dialog
        self.ai_dialogue = []
        self.max_ai_lines = 4
        try:
            self.ai_avatar = pygame.image.load("among_ai.png")
            self.ai_avatar = pygame.transform.scale(self.ai_avatar, (64, 64))
        except:
            self.ai_avatar = None

        # Démarrage serveur
        self.serveur = ServeurArbitre(broker_ip, nb_joueurs)
        self.serveur.afficher = self.custom_print
        threading.Thread(target=self.serveur.demarrer_serveur, daemon=True).start()

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                pygame.quit()
                sys.exit()
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_r and self.game_over:
                self.game_over = False
                self.serveur.demarrer_jeu()

    def update_game_state(self):
        self.connected_players = self.serveur.capteurs_connectes
        self.current_round = self.serveur.round_actuel
        self.spy = self.serveur.espion
        
        # Combiner votes round1/round2
        self.votes = {}
        if hasattr(self.serveur, 'votes_round1'):
            self.votes.update(self.serveur.votes_round1)
        if hasattr(self.serveur, 'votes_round2'):
            self.votes.update(self.serveur.votes_round2)

        # Détection fin de partie
        if not self.serveur.jeu_actif and self.current_round == 0 and self.spy:
            self.game_over = True

        # Traiter messages
        while not self.message_queue.empty():
            msg = self.message_queue.get()
            self.console_messages.append(msg)
            if len(self.console_messages) > 15:
                self.console_messages.pop(0)
            
            # Capture réponse IA
            if "[OLLAMA]" in msg and "Defense" in msg:
                try:
                    defense = msg.split(":", 2)[2].strip()
                    self.ai_dialogue.append(f"{time.strftime('%H:%M:%S')} — {defense}")
                    if len(self.ai_dialogue) > self.max_ai_lines:
                        self.ai_dialogue.pop(0)
                except:
                    pass

    def draw_section(self, title, section):
        surf = pygame.Surface((section['w'], section['h']), pygame.SRCALPHA)
        pygame.draw.rect(surf, (0, 0, 0, 192), (0, 0, section['w'], section['h']))
        title_surf = self.font_normal.render(title, True, (255, 255, 255))
        surf.blit(title_surf, (10, 10))
        self.screen.blit(surf, (section['x'], section['y']))
        return 50

    def draw_game_over(self):
        if not self.game_over:
            return

        overlay = pygame.Surface((self.WIDTH, self.HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 128))
        self.screen.blit(overlay, (0, 0))

        text = self.font_normal.render(
            f"Partie terminée! L'espion était: {self.spy}",
            True, (255, 255, 255))
        self.screen.blit(text, text.get_rect(center=(self.WIDTH//2, self.HEIGHT//2)))
        
        controls = self.font_small.render(
            "ECHAP: Quitter | R: Nouvelle partie",
            True, (200, 200, 200))
        self.screen.blit(controls, controls.get_rect(center=(self.WIDTH//2, self.HEIGHT-40)))

    def draw_players(self):
        if not self.player_objects or len(self.player_objects) != len(self.connected_players):
            self.create_player_positions()

        for player_id, player in self.player_objects.items():
            player.animation_offset = self.animation_time
            player.draw(self.screen, player_id == self.spy)
            
            name = self.font_small.render(str(player_id), True, (255, 255, 255))
            self.screen.blit(name, name.get_rect(center=(player.x, player.y + 50)))

    def create_player_positions(self):
        players = list(self.connected_players.keys())
        section = self.sections['players']
        center_x = section['x'] + section['w'] // 2
        center_y = section['y'] + section['h'] // 2
        radius = min(section['w'], section['h']) * 0.35

        self.player_objects.clear()
        for i, player_id in enumerate(players):
            angle = (2 * math.pi * i / len(players)) - math.pi/2
            x = center_x + radius * math.cos(angle)
            y = center_y + radius * math.sin(angle)
            self.player_objects[player_id] = AmongUsPlayer(
                self.COLORS[i % len(self.COLORS)], x, y)

    def draw_ai_panel(self):
        if not self.ai_dialogue:
            return

        x, y = self.WIDTH - 360, self.HEIGHT - 160
        surf = pygame.Surface((340, 140), pygame.SRCALPHA)
        pygame.draw.rect(surf, (10, 12, 20, 220), (0, 0, 340, 140), border_radius=8)

        if self.ai_avatar:
            surf.blit(self.ai_avatar, (12, 12))
        else:
            pygame.draw.circle(surf, (120, 180, 240), (44, 44), 30)

        title = self.font_normal.render("Arbitre IA", True, (220, 220, 255))
        surf.blit(title, (84, 18))

        for i, msg in enumerate(self.ai_dialogue[-self.max_ai_lines:]):
            text = self.font_small.render(msg, True, (235, 235, 235))
            surf.blit(text, (84, 52 + i * 24))

        self.screen.blit(surf, (x, y))

    def custom_print(self, message):
        """Fonction d'affichage personnalisée pour le serveur"""
        self.message_queue.put(message)
        print(message)  # Garde aussi l'affichage console

    def run(self):
        clock = pygame.time.Clock()
        while True:
            self.handle_events()
            self.update_game_state()

            # Background
            self.screen.fill((8, 8, 24))
            
            # Game elements
            self.draw_section("État", self.sections['game'])
            status = self.font_normal.render(
                f"Round {self.current_round}/{self.serveur.nb_rounds}",
                True, (255, 255, 255))
            self.screen.blit(status, (30, 70))

            self.draw_players()
            
            # Votes
            y = self.draw_section("Votes", self.sections['votes'])
            for voter, vote in self.votes.items():
                text = self.font_small.render(f"{voter} → {vote}", True, (255, 255, 255))
                self.screen.blit(text, (self.sections['votes']['x'] + 10,
                    self.sections['votes']['y'] + y))
                y += 30

            # Console
            y = self.draw_section("Console", self.sections['console'])
            for msg in self.console_messages[-15:]:
                text = self.font_small.render(msg, True, (255, 255, 255))
                self.screen.blit(text, (self.sections['console']['x'] + 10,
                    self.sections['console']['y'] + y))
                y += 20

            self.draw_ai_panel()
            
            if self.game_over:
                self.draw_game_over()
            else:
                self.animation_time += 0.05

            pygame.display.flip()
            clock.tick(60)

if __name__ == "__main__":
    IP_BROKER = "10.109.150.194"
    ArbitreDisplay(IP_BROKER).run()