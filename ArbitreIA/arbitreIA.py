#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import paho.mqtt.client as mqtt
import json
import random
import time
import threading
from collections import Counter
import requests

# Configuration Ollama
OLLAMA_URL = "http://10.103.1.12:11434/api/generate"
OLLAMA_MODEL = "gemma3:4b"

class ServeurArbitre:
    def __init__(self, broker_ip, nb_joueurs):
        self.broker_ip = broker_ip
        self.nb_joueurs = nb_joueurs
        # État du jeu
        self.capteurs_connectes = {}
        self.espion = None
        self.jeu_actif = False
        self.round_actuel = 0
        self.nb_rounds = 5  

        # Données de la partie
        self.temperatures = {}
        self.villes_attribuees = {}

        # Votes: round1 et round2 séparés
        self.votes_round1 = {}
        self.votes_round2 = {}
        self.awaiting_second_vote = False

        # Liste des villes possibles
        self.pool_villes = [
            "Chambery", "Vassieux-en-Vercors", "Annecy", "Genève", "Lyon",
            "Grenoble", "Albertville", "Aix-les-Bains", "Valence", "Saint-Étienne"
        ]

        # Configuration MQTT
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, "serveur")
        self.client.on_connect = self.quand_connecte
        self.client.on_message = self.quand_message_recu

        # Timers
        self.timer_votes = None

        # Session HTTP pour Ollama
        self.session = requests.Session()

    def afficher(self, message):
        """Affichage simple avec horodatage"""
        heure = time.strftime("%H:%M:%S")
        print(f"[{heure}] {message}")

    # ===== GESTION MQTT =====

    def quand_connecte(self, client, userdata, flags, rc):
        """Callback quand le serveur se connecte au broker"""
        if rc == 0:
            self.afficher("[OK] Serveur connecte au broker MQTT")
            client.subscribe("iot/connexion/+")
            client.subscribe("iot/temperature/+")
            client.subscribe("iot/votes/+")
            client.subscribe("iot/round_termine/+")
            self.afficher(f"[INFO] En attente de {self.nb_joueurs} capteurs...")
        else:
            self.afficher(f"[ERREUR] Connexion refusee rc={rc}")

    def quand_message_recu(self, client, userdata, msg):
        """Callback quand un message MQTT arrive"""
        try:
            topic = msg.topic
            payload = msg.payload.decode("utf-8")

            if topic.startswith("iot/connexion/"):
                capteur_id = topic.split("/")[-1]
                self.nouveau_capteur(capteur_id)

            elif topic.startswith("iot/temperature/"):
                capteur_id = topic.split("/")[-1]
                self.reception_temperature(capteur_id, payload)

            elif topic.startswith("iot/votes/"):
                capteur_id = topic.split("/")[-1]
                self.reception_vote(capteur_id, payload)

        except Exception as e:
            self.afficher(f"[ERREUR] Traitement message: {e}")

    # ===== LOGIQUE DE JEU =====

    def nouveau_capteur(self, capteur_id):
        """Quand un nouveau capteur se connecte"""
        self.afficher(f"[CONNEXION] Nouveau capteur: {capteur_id}")
        self.capteurs_connectes[capteur_id] = True

        nb_capteurs = len(self.capteurs_connectes)
        if nb_capteurs < self.nb_joueurs:
            self.afficher(f"[ATTENTE] {nb_capteurs}/{self.nb_joueurs} capteurs connectes")
        elif nb_capteurs == self.nb_joueurs and not self.jeu_actif:
            self.afficher(f"[JEU] {self.nb_joueurs} capteurs connectes! Demarrage...")
            threading.Timer(1.0, self.demarrer_jeu).start()

    def demarrer_jeu(self):
        """Lance une nouvelle partie"""
        if len(self.capteurs_connectes) < self.nb_joueurs:
            return

        self.afficher("=== DEBUT DE PARTIE ===")
        self.jeu_actif = True
        self.round_actuel = 0
        self.temperatures.clear()
        self.villes_attribuees.clear()
        self.votes_round1.clear()
        self.votes_round2.clear()
        self.awaiting_second_vote = False

        # Choisir l'espion au hasard
        ids_capteurs = list(self.capteurs_connectes.keys())
        self.espion = random.choice(ids_capteurs)
        self.afficher(f"[ESPION] Espion secret: {self.espion}")

        # Envoyer les rôles
        for capteur_id in ids_capteurs:
            role = "espion" if capteur_id == self.espion else "normal"
            self.client.publish(f"iot/role/{capteur_id}", role, qos=1)
            self.afficher(f"[ROLE] {capteur_id}: {role}")
            time.sleep(0.3)

        # Démarrer le premier round
        time.sleep(1)
        self.demarrer_round()

    def demarrer_round(self):
        """Démarre un nouveau round avec de nouvelles villes"""
        self.round_actuel += 1
        self.afficher(f"\n=== ROUND {self.round_actuel}/{self.nb_rounds} ===")

        # Attribuer de nouvelles villes aléatoires pour ce round
        ids_capteurs = list(self.capteurs_connectes.keys())
        villes_choisies = random.sample(self.pool_villes, len(ids_capteurs))

        for i, capteur_id in enumerate(ids_capteurs):
            ville = villes_choisies[i]
            self.villes_attribuees[capteur_id] = ville
            self.client.publish(f"iot/ville/{capteur_id}", ville, qos=1)
            self.afficher(f"[VILLE] {capteur_id}: {ville}")
            time.sleep(0.3)

        # Demander les températures pour ce round
        self.client.publish("iot/demande_round", str(self.round_actuel), qos=1)
        self.afficher("[INFO] Temperatures demandees...")

    def reception_temperature(self, capteur_id, payload):
        """Quand on reçoit une température d'un capteur"""
        if not self.jeu_actif or capteur_id not in self.capteurs_connectes:
            return

        ville = self.villes_attribuees.get(capteur_id, "Inconnue")
        temperature = None

        try:
            data = json.loads(payload)
            if isinstance(data, dict) and "temperature" in data:
                temperature = float(data["temperature"])
                ville = data.get("ville", ville)
            else:
                temperature = float(payload)
        except:
            try:
                temperature = float(payload)
            except:
                self.afficher(f"[ERREUR] Temperature invalide de {capteur_id}: {payload}")
                return

        # Stocker pour affichage
        if capteur_id not in self.temperatures:
            self.temperatures[capteur_id] = []
        self.temperatures[capteur_id].append({"ville": ville, "temperature": temperature, "round": self.round_actuel})

        self.afficher(f"[TEMP] Round {self.round_actuel} - {capteur_id} ({ville}): {temperature}°C")

        # Vérifier si tous les capteurs ont envoyé leur température pour ce round
        nb_temp_round = sum(1 for temps in self.temperatures.values() if len(temps) >= self.round_actuel)

        if nb_temp_round == len(self.capteurs_connectes):
            self.afficher(f"[ROUND] Toutes les temperatures recues pour le round {self.round_actuel}")

            # Si c'est le dernier round, demander le vote initial
            if self.round_actuel >= self.nb_rounds:
                self.afficher("[INFO] Dernier round termine! En attente des votes...")
                # Demander aux clients d'envoyer le vote initial
                self.client.publish("iot/demande_vote", "vote", qos=1)
                self.afficher("[INFO] Demande de vote envoyee aux capteurs (round 1)")
                # lancer timer pour clôture vote round1
                if self.timer_votes:
                    try:
                        self.timer_votes.cancel()
                    except:
                        pass
                self.timer_votes = threading.Timer(10.0, self.cloturer_votes)
                self.timer_votes.start()
            else:
                # Démarrer le prochain round après 2 secondes
                threading.Timer(2.0, self.demarrer_round).start()

    def reception_vote(self, capteur_id, payload):
        """Quand on reçoit un vote d'un capteur"""
        if not self.jeu_actif or capteur_id not in self.capteurs_connectes:
            return

        try:
            vote = json.loads(payload)
            espion_presume = vote.get("espion_presume")

            if not espion_presume:
                self.afficher(f"[ERREUR] Vote invalide (pas d'espion_presume): {payload}")
                return

            if not self.awaiting_second_vote:
                # Round 1
                self.votes_round1[capteur_id] = espion_presume
                self.afficher(f"[VOTE R1] {capteur_id} vote pour: {espion_presume}")

                if len(self.votes_round1) == len(self.capteurs_connectes):
                    # annuler timer et traiter de suite
                    if self.timer_votes:
                        try:
                            self.timer_votes.cancel()
                        except:
                            pass
                    self.afficher("[VOTES] Tous les votes (round 1) recus!")
                    threading.Timer(0.1, self.traiter_votes_round1).start()
            else:
                # Round 2
                self.votes_round2[capteur_id] = espion_presume
                self.afficher(f"[VOTE R2] {capteur_id} vote pour: {espion_presume}")

                if len(self.votes_round2) == len(self.capteurs_connectes):
                    if self.timer_votes:
                        try:
                            self.timer_votes.cancel()
                        except:
                            pass
                    self.afficher("[VOTES] Tous les votes (round 2) recus!")
                    threading.Timer(0.1, self.traiter_votes_round2).start()

        except Exception as e:
            self.afficher(f"[ERREUR] Vote invalide de {capteur_id}: {e}")

    def cloturer_votes(self):
        """Si tous les capteurs n'ont pas voté à temps"""
        if not self.jeu_actif:
            return

        if not self.awaiting_second_vote:
            # clôture du round1
            manquants = set(self.capteurs_connectes.keys()) - set(self.votes_round1.keys())
            self.afficher(f"[TIMEOUT] Round1 - Votes manquants de: {', '.join(manquants)}")
            # relance une fois
            if manquants:
                self.client.publish("iot/demande_vote", "vote", qos=1)
                self.afficher("[INFO] Relance demande de vote envoyee (round 1)")
                # on donne encore un peu de temps : relancer timer
                self.timer_votes = threading.Timer(8.0, self.cloturer_votes)
                self.timer_votes.start()
                return

            # si pas assez de votes, on annule
            if len(self.votes_round1) < max(2, len(self.capteurs_connectes) // 2):
                self.afficher("[ANNULATION] Pas assez de votes pour round1")
                self.fin_manche("AUCUN", None)
            else:
                self.traiter_votes_round1()
        else:
            # clôture du round2
            manquants = set(self.capteurs_connectes.keys()) - set(self.votes_round2.keys())
            self.afficher(f"[TIMEOUT] Round2 - Votes manquants de: {', '.join(manquants)}")
            if manquants:
                self.client.publish("iot/demande_vote", "vote", qos=1)
                self.afficher("[INFO] Relance demande de vote envoyee (round 2)")
                self.timer_votes = threading.Timer(8.0, self.cloturer_votes)
                self.timer_votes.start()
                return

            if len(self.votes_round2) < max(2, len(self.capteurs_connectes) // 2):
                self.afficher("[ANNULATION] Pas assez de votes pour round2")
                # on publie tout de même la situation
                self.fin_manche("AUCUN", None)
            else:
                self.traiter_votes_round2()

    # ===== traitement vote round1 =====

    def traiter_votes_round1(self):
        """Analyse les votes du premier tour, publie la defense et lance le second tour"""
        if not self.votes_round1:
            self.afficher("[ERREUR] Aucun vote recu au round1")
            self.fin_manche("AUCUN", None)
            return

        compteur = Counter(self.votes_round1.values())
        self.afficher("\n[DECOMPTE R1] Resultats des votes (round 1):")
        for suspect, nb in compteur.most_common():
            self.afficher(f"  - {suspect}: {nb} vote(s)")

        accuse_id, nb_votes = compteur.most_common(1)[0]
        self.afficher(f"\n[VERDICT R1] Accuse (round 1): {accuse_id} ({nb_votes} vote(s))")

        # Afficher résumé températures
        self.afficher("\n[RESUME] Temperatures par capteur:")
        for capteur_id, temps in self.temperatures.items():
            temps_str = ", ".join([f"R{t['round']}: {t['temperature']}°C ({t['ville']})" for t in temps])
            self.afficher(f"  - {capteur_id}: {temps_str}")

        # Générer la défense avec Ollama pour l'accusé
        defense_text = self.generer_defense_ollama(accuse_id)

        # Publier la défense sur le topic iot/defense (les capteurs attendent ce message)
        payload = {"capteur_id": accuse_id, "defense": defense_text}
        self.client.publish("iot/defense", json.dumps(payload, ensure_ascii=False), qos=1)
        self.afficher(f"[PUBLICATION] Defense publiee pour {accuse_id}")

        # Préparer second tour : vider votes_round2, activer flag
        self.votes_round2.clear()
        self.awaiting_second_vote = True

        # Demander second vote aux capteurs
        time.sleep(1.0)
        self.client.publish("iot/demande_vote", "vote_round2", qos=1)
        self.afficher("[INFO] Demande de vote envoyee aux capteurs (round 2)")
        # lancer timer pour clôture du round2
        if self.timer_votes:
            try:
                self.timer_votes.cancel()
            except:
                pass
        self.timer_votes = threading.Timer(15.0, self.cloturer_votes)
        self.timer_votes.start()

    # ===== traitement vote round2 =====

    def traiter_votes_round2(self):
        """Analyse les votes du second tour et décide du résultat final"""
        if not self.votes_round2:
            self.afficher("[ERREUR] Aucun vote recu au round2")
            self.fin_manche("AUCUN", None)
            return

        compteur = Counter(self.votes_round2.values())
        self.afficher("\n[DECOMPTE R2] Resultats des votes (round 2):")
        for suspect, nb in compteur.most_common():
            self.afficher(f"  - {suspect}: {nb} vote(s)")

        accuse_id_r2, nb_votes_r2 = compteur.most_common(1)[0]
        self.afficher(f"\n[VERDICT R2] Accuse final (round 2): {accuse_id_r2} ({nb_votes_r2} vote(s))")

        # Déterminer le gagnant final
        if accuse_id_r2 == self.espion:
            gagnant = "CAPTEURS"
            self.afficher(f"\n[GAGNANT] LES CAPTEURS GAGNENT! Espion demasque: {self.espion}")
        else:
            gagnant = "ESPION"
            self.afficher(f"\n[GAGNANT] L'ESPION GAGNE! Accuse a tort: {accuse_id_r2}")
            self.afficher(f"[INFO] Le vrai espion etait: {self.espion}")

        # Publier résultats complets
        resultats = {
            "gagnant": gagnant,
            "espion": self.espion,
            "accuse_round1": None,
            "accuse": accuse_id_r2,
            "votes_round1": self.votes_round1,
            "votes_round2": self.votes_round2,
            "temperatures": self.temperatures,
            "villes": self.villes_attribuees,
            "nb_rounds": self.nb_rounds
        }

        # extraire accusé round1 s'il existe
        if self.votes_round1:
            try:
                c1 = Counter(self.votes_round1.values())
                resultats["accuse_round1"] = c1.most_common(1)[0][0]
            except:
                resultats["accuse_round1"] = None

        self.client.publish("iot/resultats", json.dumps(resultats, ensure_ascii=False), qos=1)
        self.afficher("[PUBLICATION] Resultats publies (final)")

        # Reset mais sans relancer automatiquement
        self.jeu_actif = False
        self.round_actuel = 0
        self.temperatures = self.temperatures  # On garde l'historique
        self.villes_attribuees = self.villes_attribuees  # On garde l'historique
        self.votes_round1 = self.votes_round1  # On garde l'historique
        self.votes_round2 = self.votes_round2  # On garde l'historique
        self.awaiting_second_vote = False
        
        self.afficher("[INFO] Partie terminée. Appuyez sur R pour relancer une partie")

    # ===== Ollama integration pour générer une defense =====

    def generer_defense_ollama(self, accuse_id):
        """Appelle Ollama pour générer une défense courte pour l'accusé"""
        # Build prompt
        prompt_lines = [
            "Tu es un assistant neutre qui rédige une courte défense pour un capteur accusé d'être un espion.",
            f"Accuse: {accuse_id}",
            "Voici les temperatures recueillies (par capteur et round):"
        ]
        for cid, temps in sorted(self.temperatures.items()):
            temps_repr = ", ".join([f"R{t['round']}={t['temperature']}°C" for t in temps])
            prompt_lines.append(f"- {cid}: {temps_repr}")

        prompt_lines.append(
            f"\nRédige une défense honnête en 2 à 3 phrases expliquant pourquoi {accuse_id} pourrait ne pas être l'espion."
        )
        prompt_lines.append("Répond strictement en JSON avec le champ 'defense' (ex: {\"defense\": \"...\"}). Ne fournis aucun texte hors du JSON.")
        prompt = "\n".join(prompt_lines)

        self.afficher(f"[OLLAMA] Préparation requête de défense pour {accuse_id}")

        payload = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.0}
        }

        max_attempts = 3
        backoff = 1.0
        for attempt in range(1, max_attempts + 1):
            t0 = time.time()
            try:
                self.afficher(f"[OLLAMA] Attempt {attempt}/{max_attempts} - envoi (prompt {len(prompt)} bytes)")
                resp = self.session.post(OLLAMA_URL, json=payload, timeout=30)
                elapsed = time.time() - t0
                status = resp.status_code
                text = resp.text or ""
                # Truncate long responses in logs
                short_text = text[:2000] + ("...(truncated)" if len(text) > 2000 else "")
                self.afficher(f"[OLLAMA] HTTP {status} en {elapsed:.2f}s - réponse (troncée): {short_text}")

                if status != 200:
                    self.afficher(f"[OLLAMA][WARN] Statut inattendu {status}, attempt={attempt}")
                    # retry with backoff
                    if attempt < max_attempts:
                        time.sleep(backoff)
                        backoff *= 2
                        continue
                    else:
                        break

                # Parse JSON response from Ollama API
                try:
                    result = resp.json()
                except Exception as e:
                    self.afficher(f"[OLLAMA][ERROR] JSON decode failed: {e}")
                    # include raw text as fallback
                    result = {"response": text}

                # Ollama returns 'response' string when stream=False; it may contain JSON
                response_text = ""
                if isinstance(result, dict):
                    response_text = (result.get("response") or result.get("result") or "").strip()
                elif isinstance(result, str):
                    response_text = result.strip()
                else:
                    response_text = str(result)

                # Try to parse the model output as JSON
                defense = None
                if response_text:
                    try:
                        parsed = json.loads(response_text)
                        if isinstance(parsed, dict):
                            defense = parsed.get("defense") or parsed.get("message") or None
                        else:
                            defense = str(parsed)
                    except Exception:
                        # Not JSON: use the raw response_text
                        defense = response_text

                # Final cleanup
                if defense is None:
                    defense = "Je ne suis pas l'espion, mes temperatures sont coherentes."
                elif not isinstance(defense, str):
                    defense = str(defense)

                defense = defense.strip().strip('"')
                self.afficher(f"[OLLAMA] Defense recuperee (len={len(defense)}): {defense[:1000]}{('...') if len(defense)>1000 else ''}")
                return defense

            except requests.RequestException as e:
                elapsed = time.time() - t0
                self.afficher(f"[OLLAMA][ERROR] Request failed (attempt {attempt}) after {elapsed:.2f}s: {e}")
                if attempt < max_attempts:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                else:
                    break
            except Exception as e:
                self.afficher(f"[OLLAMA][ERROR] Unexpected error: {e}")
                break

        # If we reach here, all attempts failed
        self.afficher("[OLLAMA][ERROR] Echec de generation apres plusieurs tentatives")
        return "Je ne suis pas l'espion, mes temperatures sont coherentes."

    def fin_manche(self, gagnant, accuse):
        """Termine la partie et prépare la suivante (utilisé en cas d'annulation)"""
        resultats = {
            "gagnant": gagnant,
            "espion": self.espion,
            "accuse": accuse,
            "votes_round1": self.votes_round1,
            "votes_round2": self.votes_round2,
            "temperatures": self.temperatures,
            "villes": self.villes_attribuees,
            "nb_rounds": self.nb_rounds
        }
        self.client.publish("iot/resultats", json.dumps(resultats, ensure_ascii=False), qos=1)
        self.afficher("[PUBLICATION] Resultats publies (annulation ou cas particulier)")

        # Réinitialiser
        self.jeu_actif = False
        self.round_actuel = 0
        self.temperatures.clear()
        self.villes_attribuees.clear()
        self.votes_round1.clear()
        self.votes_round2.clear()
        self.awaiting_second_vote = False

        self.afficher("[INFO] Prochaine partie dans 15 secondes...\n")
        threading.Timer(15.0, self.demarrer_jeu).start()

    def demarrer_serveur(self):
        """Démarre le serveur MQTT"""
        self.afficher("[DEMARRAGE] Serveur en cours...")
        try:
            self.client.connect(self.broker_ip, 1883, 60)
            self.client.loop_forever()
        except Exception as e:
            self.afficher(f"[ERREUR] {e}")


# ===== PROGRAMME PRINCIPAL =====
if __name__ == "__main__":
    IP_BROKER = "10.109.150.194"

    print("=== SERVEUR DE JEU IoT (MODE VOTE DOUBLE) ===")
    print(f"Broker: {IP_BROKER}")
    print("Regles: Chaque round change de ville, les capteurs votent a la fin (2 tours)\n")

    # Demander le nombre de joueurs
    while True:
        try:
            nb_joueurs = int(input("Nombre de joueurs (2-10): "))
            if 2 <= nb_joueurs <= 10:
                break
            else:
                print("Veuillez entrer un nombre entre 2 et 10")
        except ValueError:
            print("Veuillez entrer un nombre valide")

    print(f"\nConfiguration: {nb_joueurs} joueurs")
    print("Demarrage du serveur...\n")

    serveur = ServeurArbitre(IP_BROKER, nb_joueurs)
    try:
        serveur.demarrer_serveur()
    except KeyboardInterrupt:
        print("\nArret du serveur")
