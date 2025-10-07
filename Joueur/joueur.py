import paho.mqtt.client as mqtt
from paho.mqtt.client import CallbackAPIVersion
import requests
import sys
import json
import random
import threading
import pygame
from pygame.locals import *

BROKER_IP = "10.109.150.194"
BROKER_PORT = 1883
OLLAMA_URL = "http://10.103.1.12:11434/api/generate"
OLLAMA_MODEL = "gemma3:4b"
OLLAMA_MODEL_ESPION = "gpt-oss:20b"
NB_ROUNDS = 5

class Capteur:
    def __init__(self, capteur_id, broker_ip=BROKER_IP):
        self.id = capteur_id
        self.broker_ip = broker_ip
        self.role = None
        self.ville = None
        
        self.temperatures = {}
        self.mes_temperatures = []
        self.round_count = 0
        self.vote_envoye = False
        self.defense_recue = None
        self.vote_round = 1  # 1 = premier vote, 2 = second vote
        
        self.client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=f"capteur_{self.id}"
        )
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

        # Pygame
        self.screen = None
        self.font_big = None
        self.font_medium = None
        self.font_small = None
        self.results = None
        self.all_capteurs = set()
        self.avatar_assignments = {}
        self.next_avatar_index = 0

        self.avatar_filenames = ['among_blue.png', 'among_grn.png', 'among_red.png', 'among_yllw.png']
        self.avatar_images = [None] * len(self.avatar_filenames)
        self.scaled_avatars = {}
        self.stars = [(random.randint(0, 1200), random.randint(0, 800)) for _ in range(50)]
        
        self.session = requests.Session()
        self._geocode_cache = {}

    def log(self, msg):
        print(f"[{self.id}] {msg}")

    def get_meteo(self, ville):
        try:
            if ville in self._geocode_cache:
                lat, lon = self._geocode_cache[ville]
            else:
                r = self.session.get(
                    "https://geocoding-api.open-meteo.com/v1/search",
                    params={"name": ville, "count": 1},
                    timeout=5
                )
                r.raise_for_status()
                geo = r.json().get("results")
                if not geo:
                    raise ValueError("no geocode results")
                geo0 = geo[0]
                lat, lon = geo0["latitude"], geo0["longitude"]
                self._geocode_cache[ville] = (lat, lon)

            r = self.session.get(
                "https://api.open-meteo.com/v1/forecast",
                params={"latitude": lat, "longitude": lon, "current_weather": "true"},
                timeout=5
            )
            r.raise_for_status()
            temp = r.json().get("current_weather", {}).get("temperature")

            if temp is None:
                raise ValueError("no temperature in response")

            if self.role == "espion":
                temp += random.uniform(-5, 5)
                self.log(f"[ESPION] Temperature modifiee: {round(temp, 1)} degres")

            return round(float(temp), 1)
        except Exception as e:
            self.log(f"[ERREUR] API meteo: {e}")
            return None

    def analyser_defense_ollama(self):
        """Analyse la crédibilité de la défense reçue"""
        try:
            if not self.defense_recue:
                return None

            prompt = f"Tu es un detective expert en analyse comportementale. Analyse la defense d'un capteur accusé d'être un espion.\n\n"
            prompt += f"Voici les températures du capteur accusé ({self.defense_recue['capteur_id']}):\n"
            if self.defense_recue['capteur_id'] in self.temperatures:
                for i, t in enumerate(self.temperatures[self.defense_recue['capteur_id']]):
                    prompt += f"Round {i+1}: {t} degres\n"

            prompt += "\nTemperatures des autres capteurs:\n"
            for cid, temps in sorted(self.temperatures.items()):
                if cid != self.defense_recue['capteur_id']:
                    prompt += f"\nCapteur {cid}:\n"
                    for i, t in enumerate(temps):
                        prompt += f"Round {i+1}: {t} degres\n"
            
            prompt += f"\nLe capteur accusé s'est défendu ainsi:\n"
            prompt += f'"{self.defense_recue["defense"]}"\n\n'
            prompt += "Analyse la crédibilité de cette défense. Est-elle sincère ou suspecte? "
            prompt += "Reponds uniquement en JSON avec les champs 'credible' (boolean) et 'analyse' (string). Ne fournis aucun texte hors du JSON."

            response = self.session.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "format": "json",
                    "stream": False
                },
                timeout=60
            )

            if response.status_code == 200:
                result = response.json()
                reponse_ia = result.get("response", "").strip()
                self.log(f"[OLLAMA] Analyse défense: {reponse_ia}")
                
                try:
                    parsed = json.loads(reponse_ia)
                    return parsed
                except json.JSONDecodeError:
                    self.log("[OLLAMA] Erreur de parsing JSON analyse")
                    return None
                    
            return None
                
        except Exception as e:
            self.log(f"[ERREUR] Ollama analyse défense: {e}")
            return None

    def demander_vote_ollama(self, avec_defense=False):
        """Demande à Ollama qui voter"""
        try:
            # Construire le prompt
            prompt = f"Tu es un detective qui analyse des temperatures mesurees par des capteurs. Un des capteurs est un espion qui envoie de fausses donnees.\n\n"
            prompt += f"Mes temperatures (capteur {self.id}):\n"
            for i, t in enumerate(self.mes_temperatures):
                prompt += f"Round {i+1}: {t} degres\n"
            
            prompt += "\nTemperatures des autres capteurs:\n"
            for cid, temps in sorted(self.temperatures.items()):
                prompt += f"\nCapteur {cid}:\n"
                for i, t in enumerate(temps):
                    prompt += f"Round {i+1}: {t} degres\n"
            
            if avec_defense and self.defense_recue:
                self.defense_analyse = self.analyser_defense_ollama()
                prompt += f"\nLe capteur accuse ({self.defense_recue['capteur_id']}) s'est defend ainsi:\n"
                prompt += f'"{self.defense_recue["defense"]}"\n\n'
                if self.defense_analyse:
                    prompt += f"Analyse de la défense: {self.defense_analyse.get('analyse', '')}\n"
                    prompt += f"La défense semble {'crédible' if self.defense_analyse.get('credible') else 'suspecte'}.\n\n"
                prompt += "En tenant compte de cette defense et de son analyse, qui penses-tu etre l'espion? "
            else:
                prompt += "\nQuel capteur penses-tu etre l'espion? Analyse les ecarts de temperature et "
            prompt += "Reponds uniquement en JSON avec le champ 'espion_presume' contenant l'ID du capteur suspect (ex: {\"espion_presume\": \"bot\"}). Ne fournis aucun texte hors du JSON."
            
            self.log("[OLLAMA] Envoi de la demande de vote")
            
            response = self.session.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "format": "json",
                    "stream": False
                },
                timeout=60
            )
            
            if response.status_code == 200:
                result = response.json()
                reponse_ia = result.get("response", "").strip()
                self.log(f"[OLLAMA] Reponse IA: {reponse_ia}")
                
                # Parser la réponse JSON
                try:
                    parsed = json.loads(reponse_ia)
                    espion_presume = parsed.get("espion_presume")
                    if espion_presume:
                        return espion_presume
                except json.JSONDecodeError:
                    self.log("[OLLAMA] Erreur de parsing JSON")
                
                # Fallback si pas trouvé
                self.log("[OLLAMA] ID non trouve dans la reponse, vote aleatoire")
                return random.choice(list(self.temperatures.keys())) if self.temperatures else "aucun"
            else:
                self.log(f"[ERREUR] Ollama erreur HTTP: {response.status_code}")
                return None
                
        except Exception as e:
            self.log(f"[ERREUR] Ollama: {e}")
            return None

    def generer_defense_ollama(self):
        """Génère une défense via Ollama si accusé"""
        try:
            prompt = f"Tu es le capteur {self.id} accuse d'etre un espion. Voici tes temperatures:\n"
            for i, t in enumerate(self.mes_temperatures):
                prompt += f"Round {i+1}: {t} degres\n"
            
            prompt += "\nTemperatures des autres capteurs:\n"
            for cid, temps in sorted(self.temperatures.items()):
                prompt += f"\nCapteur {cid}:\n"
                for i, t in enumerate(temps):
                    prompt += f"Round {i+1}: {t} degres\n"
            
            prompt += f"\nRédige une défense honnête en 2 à 3 phrases expliquant pourquoi {self.id} pourrait ne pas être l'espion.\n"
            prompt += "Reponds uniquement en JSON avec le champ 'defense' contenant le texte de la defense (ex: {\"defense\": \"Texte de defense\"}). Ne fournis aucun texte hors du JSON."
            
            self.log("[OLLAMA] Generation de la defense")
            
            response = self.session.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL_ESPION,
                    "prompt": prompt,
                    "format": "json",
                    "stream": False
                },
                timeout=60
            )
            
            if response.status_code == 200:
                result = response.json()
                reponse_ia = result.get("response", "").strip()
                self.log(f"[OLLAMA] Reponse IA: {reponse_ia}")
                
                # Parser la réponse JSON
                try:
                    parsed = json.loads(reponse_ia)
                    defense = parsed.get("defense", "").strip()
                    if defense:
                        return defense
                except json.JSONDecodeError:
                    self.log("[OLLAMA] Erreur de parsing JSON")
                
                return "Je ne suis pas l'espion, mes temperatures sont coherentes."
            else:
                self.log(f"[ERREUR] Ollama erreur HTTP: {response.status_code}")
                return "Je ne suis pas l'espion, mes temperatures sont coherentes."
                
        except Exception as e:
            self.log(f"[ERREUR] Ollama defense: {e}")
            return "Je ne suis pas l'espion, mes temperatures sont coherentes."

    def voter(self):
        if self.vote_envoye:
            return
        
        self.log(f"[VOTE] Debut du vote round {self.vote_round}")
        
        # Voter avec ou sans défense selon le round
        avec_defense = self.vote_round == 2 and self.defense_recue is not None
        espion_presume = self.demander_vote_ollama(avec_defense=avec_defense)

        # Build candidate list excluding self
        candidates = list({*self.temperatures.keys(), *self.all_capteurs})
        candidates = [c for c in candidates if c != self.id]

        if not espion_presume:
            self.log("[VOTE] Ollama indisponible, choix aléatoire parmi candidats")
            espion_presume = random.choice(candidates) if candidates else "aucun"
        else:
            # If IA suggests self, prevent auto-vote
            if str(espion_presume) == str(self.id):
                self.log(f"[VOTE] IA propose autop-vote ({espion_presume}) - refuse")
                espion_presume = random.choice(candidates) if candidates else "aucun"
            else:
                # ensure suggested id is known; if unknown, fall back
                if candidates and espion_presume not in candidates:
                    self.log(f"[VOTE] IA propose un id inconnu ({espion_presume}) - fallback")
                    espion_presume = random.choice(candidates) if candidates else "aucun"
        
        vote = {"votant": self.id, "espion_presume": espion_presume, "round": self.vote_round}
        self.client.publish(f"iot/votes/{self.id}", json.dumps(vote), qos=1)
        self.log(f"[VOTE] Vote round {self.vote_round} transmis pour: {espion_presume}")
        self.vote_envoye = True

    def on_connect(self, client, userdata, flags, rc, properties):
        if rc == 0:
            self.log("[OK] Connexion etablie")
            client.subscribe(f"iot/role/{self.id}")
            client.subscribe(f"iot/ville/{self.id}")
            client.subscribe("iot/demande_vote")
            client.subscribe("iot/defense")
            client.subscribe("iot/temperature/#")
            client.subscribe("iot/resultats")
            client.publish(f"iot/connexion/{self.id}", "connected", qos=1)
        else:
            self.log(f"[ERREUR] Connexion echouee: code {rc}")

    def envoyer_temperature(self):
        if not self.ville:
            return
        temp = self.get_meteo(self.ville)
        if temp:
            data = {"ville": self.ville, "temperature": temp, "round": self.round_count}
            self.client.publish(f"iot/temperature/{self.id}", json.dumps(data), qos=1)
            self.mes_temperatures.append(temp)
            self.log(f"[TEMP] Round {self.round_count}: {temp} degres pour {self.ville}")
        else:
            self.log("[ERREUR] Recuperation temperature impossible")

    def on_message(self, client, userdata, msg):
        payload = msg.payload.decode("utf-8")

        if msg.topic == f"iot/role/{self.id}":
            self.role = payload.strip().lower()
            self.log(f"[ROLE] Assigne: {self.role}")
            self.results = None
            self.vote_round = 1
            self.defense_recue = None

        elif msg.topic == f"iot/ville/{self.id}":
            self.ville = payload.strip()
            self.round_count += 1
            self.log(f"[VILLE] Round {self.round_count}: {self.ville}")
            threading.Thread(target=self.envoyer_temperature, daemon=True).start()

        elif msg.topic.startswith("iot/temperature/"):
            capteur_id = msg.topic.split("/")[-1]
            if capteur_id == self.id:
                return
            
            self.all_capteurs.add(capteur_id)
            
            try:
                data = json.loads(payload)
                temp = data.get("temperature")
                round_num = data.get("round", 0)
                
                if temp is not None:
                    if capteur_id not in self.temperatures:
                        self.temperatures[capteur_id] = []
                    self.temperatures[capteur_id].append(temp)
                    self.log(f"[RECU] {capteur_id} Round {round_num}: {temp} degres")
                    
                    if self.round_count >= NB_ROUNDS and not self.vote_envoye:
                        try:
                            min_mesures = min(len(t) for t in self.temperatures.values()) if self.temperatures else 0
                        except ValueError:
                            min_mesures = 0
                        if len(self.mes_temperatures) >= NB_ROUNDS and min_mesures >= 0:
                            threading.Timer(2.0, self.voter).start()
            except:
                pass

        elif msg.topic == "iot/demande_vote":
            self.log("[SERVEUR] Demande de vote recue")
            if not self.vote_envoye:
                threading.Timer(0.5, self.voter).start()

        elif msg.topic == "iot/defense":
            try:
                data = json.loads(payload)
                self.defense_recue = data
                self.log(f"[DEFENSE] Recu de {data['capteur_id']}: {data['defense']}")
                
                # Préparer le second vote
                self.vote_envoye = False
                self.vote_round = 2
                
            except:
                pass

        elif msg.topic == "iot/resultats":
            try:
                res = json.loads(payload)
                self.results = {
                    "gagnant": res.get("gagnant", ""),
                    "espion": res.get("espion", ""),
                    "accuse": res.get("accuse", ""),
                    "votes": res.get("votes", {}),
                    "votes_round2": res.get("votes_round2", {})
                }
                
                self.log("=" * 50)
                self.log(f"[RESULTATS] Gagnant: {self.results['gagnant']}")
                self.log(f"[RESULTATS] Espion reel: {self.results['espion']}")
                self.log(f"[RESULTATS] Accuse round 1: {res.get('accuse_round1', 'N/A')}")
                self.log(f"[RESULTATS] Accuse round 2: {self.results['accuse']}")
                
                if self.results['votes']:
                    self.log("[RESULTATS] Votes round 1:")
                    for votant, suspect in self.results['votes'].items():
                        self.log(f"  {votant} -> {suspect}")
                
                if self.results.get('votes_round2'):
                    self.log("[RESULTATS] Votes round 2:")
                    for votant, suspect in self.results['votes_round2'].items():
                        self.log(f"  {votant} -> {suspect}")
                
                if self.id == self.results['espion']:
                    if self.results['gagnant'] == "ESPION":
                        self.log("[MOI] Espion victoire")
                    else:
                        self.log("[MOI] Espion detecte")
                elif self.id == self.results['accuse']:
                    self.log("[MOI] Accuse a tort")
                else:
                    if self.results['gagnant'] == "CAPTEURS":
                        self.log("[MOI] Capteur victoire")
                    else:
                        self.log("[MOI] Capteur defaite")
                
                self.log("=" * 50)
                
                # Reset
                self.temperatures.clear()
                self.mes_temperatures.clear()
                self.round_count = 0
                self.vote_envoye = False
                self.vote_round = 1
                self.defense_recue = None
                self.role = None
                self.ville = None
                self.all_capteurs.clear()
                self.avatar_assignments.clear()
                self.next_avatar_index = 0
                self.scaled_avatars.clear()
                
            except:
                self.log(f"[RESULTATS] {payload}")

    def assign_avatar_index(self, cid):
        if cid not in self.avatar_assignments:
            self.avatar_assignments[cid] = self.next_avatar_index % len(self.avatar_images)
            self.next_avatar_index += 1
        return self.avatar_assignments[cid]

    def draw_text(self, text, x, y, color=(255, 255, 255), font=None):
        # placeholder: UI moved to ui.py
        pass

    def start(self):
        try:

            # Initialiser l'UI en premier pour s'assurer que la fenêtre s'affiche
            try:
                import ui
                ui.init_ui(self, NB_ROUNDS)
                self.log("[UI] Initialisation OK")
            except Exception as e:
                # fallback minimal init
                self.log(f"[UI] Initialisation échouée: {e} - fallback minimal")
                pygame.init()
                self.screen = pygame.display.set_mode((1200, 800))
                pygame.display.set_caption(f"Capteur {self.id}")
                self.font_big = pygame.font.Font(None, 60)
                self.font_medium = pygame.font.Font(None, 40)
                self.font_small = pygame.font.Font(None, 24)

            # Connexion MQTT après l'UI (évite blocage si réseau lent)
            self.log(f"[DEMARRAGE] Connexion {self.broker_ip}:{BROKER_PORT}")
            try:
                self.client.connect(self.broker_ip, BROKER_PORT, 60)
                self.client.loop_start()
            except Exception as e:
                self.log(f"[MQTT] Erreur de connexion (non bloquant): {e}")

            clock = pygame.time.Clock()

            running = True
            while running:
                for event in pygame.event.get():
                    if event.type == QUIT:
                        running = False
                try:
                    import ui
                    ui.draw_frame(self, NB_ROUNDS)
                except Exception:
                    # fallback simple draw to avoid crash
                    pass
                pygame.display.flip()
                clock.tick(30)

        except KeyboardInterrupt:
            self.log("[ARRET] Interruption utilisateur")
        finally:
            self.client.loop_stop()
            self.client.disconnect()
            if self.screen:
                pygame.quit()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python joueur.py <id> [broker_ip]")
        sys.exit(1)

    capteur_id = sys.argv[1]
    broker = sys.argv[2] if len(sys.argv) >= 3 else BROKER_IP

    capteur = Capteur(capteur_id, broker)
    capteur.start()