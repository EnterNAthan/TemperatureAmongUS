#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import paho.mqtt.client as mqtt
import json
import random
import time
import threading
from collections import Counter


class ServeurArbitre:
    def __init__(self, broker_ip):
        self.broker_ip = broker_ip
        # État du jeu
        self.capteurs_connectes = {}    
        self.espion = None              
        self.jeu_actif = False        
        # Données de la partie
        self.temperatures = {}
        self.villes_attribuees = {}
        self.votes_recus = {}  # {capteur_id: espion_presume}
        
        # Liste des villes possibles
        self.pool_villes = [
            "Chambery", "Vassieux-en-Vercors", "Annecy", "Genève", "Lyon"
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
            client.subscribe("iot/votes/+")  # S'abonner aux votes
            self.afficher("[INFO] En attente des capteurs...")
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
        if nb_capteurs < 2:
            self.afficher(f"[ATTENTE] {nb_capteurs}/4 capteurs connectes")
        elif nb_capteurs == 2 and not self.jeu_actif:
            self.afficher("[JEU] 4 capteurs connectes! Demarrage...")
            threading.Timer(1.0, self.demarrer_jeu).start()
            
    def demarrer_jeu(self):
        """Lance une nouvelle partie"""
        if len(self.capteurs_connectes) < 2:
            return
            
        self.afficher("=== DEBUT DE PARTIE ===")
        self.jeu_actif = True
        self.temperatures.clear()
        self.villes_attribuees.clear()
        self.votes_recus.clear()
        
        # 1. Choisir l'espion au hasard
        ids_capteurs = list(self.capteurs_connectes.keys())
        self.espion = random.choice(ids_capteurs)
        self.afficher(f"[ESPION] Espion secret: {self.espion}")
        
        # 2. Attribuer une ville différente à chaque capteur
        villes_choisies = random.sample(self.pool_villes, 4)
        
        for i, capteur_id in enumerate(ids_capteurs):
            role = "espion" if capteur_id == self.espion else "normal"
            self.client.publish(f"iot/role/{capteur_id}", role, qos=1)
            self.afficher(f"[ROLE] {capteur_id}: {role}")
            
            ville = villes_choisies[i]
            self.villes_attribuees[capteur_id] = ville
            time.sleep(0.5)  
            self.client.publish(f"iot/ville/{capteur_id}", ville, qos=1)
            self.afficher(f"[VILLE] {capteur_id}: {ville}")
        
        # 3. Les capteurs vont maintenant envoyer automatiquement leurs températures
        # et voter après 5 rounds
        self.afficher("[INFO] Phase de collecte de temperatures...")
        
        # Timer de sécurité pour attendre les votes (5 rounds * 5 sec + marge)
        self.timer_votes = threading.Timer(35.0, self.cloturer_votes)
        self.timer_votes.start()

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
        
        # Stocker seulement pour affichage
        if capteur_id not in self.temperatures:
            self.temperatures[capteur_id] = []
        self.temperatures[capteur_id].append({"ville": ville, "temperature": temperature})
        
        nb_mesures = len(self.temperatures[capteur_id])
        self.afficher(f"[TEMP] {capteur_id} ({ville}): {temperature}°C (mesure {nb_mesures})")

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
            
            if len(self.votes_recus) >= 2:
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
        
        self.afficher("[ANALYSE] Votes recus:")
        for capteur_id, espion_presume in self.votes_recus.items():
            self.afficher(f"  - {capteur_id} vote pour: {espion_presume}")
        
        self.afficher("\n[DECOMPTE] Resultats des votes:")
        for suspect, nb_votes in compteur.most_common():
            self.afficher(f"  - {suspect}: {nb_votes} vote(s)")
        
        # Déterminer le plus voté
        accuse_id, nb_votes = compteur.most_common(1)[0]
        
        self.afficher(f"\n[VERDICT] Accuse: {accuse_id} ({nb_votes} vote(s))")
        
        # Déterminer le gagnant
        if accuse_id == self.espion:
            gagnant = "CAPTEURS"
            self.afficher(f"[GAGNANT] LES CAPTEURS GAGNENT! Espion demasque: {self.espion}")
        else:
            gagnant = "ESPION"
            self.afficher(f"[GAGNANT] L'ESPION GAGNE! Accuse a tort: {accuse_id}")
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
            "temperatures": {k: v[-1] if v else None for k, v in self.temperatures.items()},
            "villes": self.villes_attribuees
        }
        self.client.publish("iot/resultats", json.dumps(resultats, ensure_ascii=False), qos=1)
        self.afficher("[PUBLICATION] Resultats publies")
        
        # Réinitialiser pour la prochaine partie
        self.jeu_actif = False
        self.temperatures.clear()
        self.villes_attribuees.clear()
        self.votes_recus.clear()
        
        # Programmer la prochaine partie
        self.afficher("[INFO] Prochaine partie dans 10 secondes...\n")
        threading.Timer(10.0, self.demarrer_jeu).start()

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
    print("Regles: Les capteurs analysent et votent pour designer l'espion")
    print("Demarrage...\n")
    
    serveur = ServeurArbitre(IP_BROKER)
    try:
        serveur.demarrer_serveur()
    except KeyboardInterrupt:
        print("\nArret du serveur")