#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import paho.mqtt.client as mqtt
import json
import random
import time
import threading
from collections import Counter


class ServeurArbitre:
    def __init__(self, broker_ip, nb_joueurs):
        self.broker_ip = broker_ip
        self.nb_joueurs = nb_joueurs
        # État du jeu
        self.capteurs_connectes = {}    
        self.espion = None              
        self.jeu_actif = False
        self.round_actuel = 0
        self.nb_rounds = 5  # Nombre de rounds par partie
        
        # Données de la partie
        self.temperatures = {}
        self.villes_attribuees = {}
        self.votes_recus = {}
        
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
        self.timer_fin_manche = None
        self.timer_votes = None

    def afficher(self, message):
        """Affichage avec horodatage"""
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
            client.subscribe("iot/round_termine/+")  # Pour savoir quand un capteur a fini son round
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
        self.votes_recus.clear()
        
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
            
            # Si c'est le dernier round, attendre les votes
            if self.round_actuel >= self.nb_rounds:
                self.afficher("[INFO] Dernier round termine! En attente des votes...")
                # Prompt clients to send votes immediately, then start a vote timeout
                self.client.publish("iot/demande_vote", "vote", qos=1)
                self.afficher("[INFO] Demande de vote envoyee aux capteurs")
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
            
            if espion_presume:
                self.votes_recus[capteur_id] = espion_presume
                self.afficher(f"[VOTE] {capteur_id} vote pour: {espion_presume}")
                
                # Si tous les capteurs ont voté, évaluer immédiatement
                if len(self.votes_recus) == len(self.capteurs_connectes):
                    if self.timer_votes:
                        self.timer_votes.cancel()
                    self.afficher("[VOTES] Tous les votes recus!")
                    self.evaluer_votes()
        except Exception as e:
            self.afficher(f"[ERREUR] Vote invalide de {capteur_id}: {e}")

    def cloturer_votes(self):
        """Si tous les capteurs n'ont pas voté à temps"""
        if self.jeu_actif and len(self.votes_recus) < len(self.capteurs_connectes):
            manquants = set(self.capteurs_connectes.keys()) - set(self.votes_recus.keys())
            self.afficher(f"[TIMEOUT] Votes manquants de: {', '.join(manquants)}")
            # Ask again once more to give stragglers a chance
            if manquants:
                self.client.publish("iot/demande_vote", "vote", qos=1)
                self.afficher("[INFO] Relance demande de vote envoyee")

            if len(self.votes_recus) >= max(2, len(self.capteurs_connectes) // 2):
                self.evaluer_votes()
            else:
                self.afficher("[ANNULATION] Pas assez de votes")
                self.fin_manche("AUCUN", None)

    def evaluer_votes(self):
        """Détermine qui gagne en comptant les votes"""
        if not self.votes_recus:
            self.afficher("[ERREUR] Aucun vote recu")
            self.fin_manche("AUCUN", None)
            return
        
        # Compter les votes
        compteur = Counter(self.votes_recus.values())
        
        self.afficher("\n[ANALYSE] Votes recus:")
        for capteur_id, espion_presume in self.votes_recus.items():
            self.afficher(f"  - {capteur_id} vote pour: {espion_presume}")
        
        self.afficher("\n[DECOMPTE] Resultats des votes:")
        for suspect, nb_votes in compteur.most_common():
            self.afficher(f"  - {suspect}: {nb_votes} vote(s)")
        
        # Déterminer le plus voté
        accuse_id, nb_votes = compteur.most_common(1)[0]
        
        self.afficher(f"\n[VERDICT] Accuse: {accuse_id} ({nb_votes} vote(s))")
        
        # Afficher un résumé des températures
        self.afficher("\n[RESUME] Temperatures par round:")
        for capteur_id, temps in self.temperatures.items():
            temps_str = ", ".join([f"R{t['round']}: {t['temperature']}°C ({t['ville']})" for t in temps])
            self.afficher(f"  - {capteur_id}: {temps_str}")
        
        # Déterminer le gagnant
        if accuse_id == self.espion:
            gagnant = "CAPTEURS"
            self.afficher(f"\n[GAGNANT] LES CAPTEURS GAGNENT! Espion demasque: {self.espion}")
        else:
            gagnant = "ESPION"
            self.afficher(f"\n[GAGNANT] L'ESPION GAGNE! Accuse a tort: {accuse_id}")
            self.afficher(f"[INFO] Le vrai espion etait: {self.espion}")
        
        self.fin_manche(gagnant, accuse_id)

    def fin_manche(self, gagnant, accuse):
        """Termine la partie et prépare la suivante"""
        # Publier les résultats complets
        resultats = {
            "gagnant": gagnant,
            "espion": self.espion,
            "accuse": accuse,
            "votes": self.votes_recus,
            "temperatures": self.temperatures,
            "villes": self.villes_attribuees,
            "nb_rounds": self.nb_rounds
        }
        self.client.publish("iot/resultats", json.dumps(resultats, ensure_ascii=False), qos=1)
        self.afficher("[PUBLICATION] Resultats publies")
        
        # Réinitialiser pour la prochaine partie
        self.jeu_actif = False
        self.round_actuel = 0
        self.temperatures.clear()
        self.villes_attribuees.clear()
        self.votes_recus.clear()
        
        # Programmer la prochaine partie
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
    
    print("=== SERVEUR DE JEU IoT (MODE VOTE) ===")
    print(f"Broker: {IP_BROKER}")
    print("Regles: Chaque round change de ville, les capteurs votent a la fin\n")
    
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