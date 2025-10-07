#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import paho.mqtt.client as mqtt
import json
import random
import time
from datetime import datetime
import threading

class ServeurArbitre:
    def __init__(self, broker_host="localhost", broker_port=1883):
        self.broker_host = broker_host
        self.broker_port = broker_port
        
        # État du jeu
        self.capteurs_connectes = {}  # {id: {"ip": "x.x.x.x", "role": "normal/espion", "connecte": True}}
        self.temperatures_recues = {}  # {id: [temp1, temp2, temp3, temp4, temp5]}
        self.votes_recus = {}         # {id_voteur: id_suspecte}
        
        self.espion_choisi = None
        self.jeu_en_cours = False
        self.round_actuel = 0
        self.max_rounds = 5
        
        # MQTT Client
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id="serveur_arbitre")
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        
        # Logging
        self.log_file = f"serveur_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        
    def log(self, message):
        """Système de logging"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_msg = f"[{timestamp}] [SERVEUR] {message}"
        print(log_msg)
        
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(log_msg + "\n")
    
    def on_connect(self, client, userdata, flags, rc):
        """Callback de connexion au broker"""
        if rc == 0:
            self.log(f"✅ Serveur connecté au broker {self.broker_host}:{self.broker_port}")
            
            # S'abonner aux topics nécessaires
            topics = [
                "iot/connexion/+",              # Connexions des capteurs
                "iot/capteurs/+/temperature",   # Températures des capteurs
                "iot/votes/+",                  # Votes des capteurs
                "iot/ping/+",                   # Ping des capteurs
            ]
            
            for topic in topics:
                client.subscribe(topic)
                self.log(f"📡 Abonné à: {topic}")
            
            # Publier que le serveur est prêt
            client.publish("iot/serveur/status", "ready", retain=True)
            self.log("📢 Serveur prêt - En attente des capteurs...")
            
        else:
            self.log(f"❌ Échec de connexion au broker: {rc}")
    
    def on_message(self, client, userdata, msg):
        """Callback de réception des messages"""
        try:
            topic = msg.topic
            message = msg.payload.decode('utf-8')
            
            # Connexion d'un capteur
            if topic.startswith("iot/connexion/"):
                capteur_id = topic.split("/")[-1]
                self.gerer_connexion_capteur(capteur_id, message)
            
            # Réception température
            elif topic.startswith("iot/capteurs/") and topic.endswith("/temperature"):
                capteur_id = topic.split("/")[2]
                self.gerer_temperature(capteur_id, float(message))
            
            # Réception vote
            elif topic.startswith("iot/votes/"):
                voteur_id = topic.split("/")[-1]
                vote_pour = message
                self.gerer_vote(voteur_id, vote_pour)
                
            # Ping capteur
            elif topic.startswith("iot/ping/"):
                capteur_id = topic.split("/")[-1]
                self.gerer_ping(capteur_id)
                
        except Exception as e:
            self.log(f"❌ Erreur traitement message {topic}: {e}")
    
    def gerer_connexion_capteur(self, capteur_id, info_connexion):
        """Gérer la connexion d'un nouveau capteur"""
        self.log(f"🔌 Connexion capteur: {capteur_id} - {info_connexion}")
        
        # Extraire l'IP si fournie
        ip_capteur = "unknown"
        if "from" in info_connexion:
            ip_capteur = info_connexion.split("from ")[-1].strip()
        
        self.capteurs_connectes[capteur_id] = {
            "ip": ip_capteur,
            "role": None,
            "connecte": True,
            "derniere_activite": datetime.now()
        }
        
        # Vérifier si on peut démarrer le jeu
        if len(self.capteurs_connectes) == 4 and not self.jeu_en_cours:
            self.demarrer_jeu()
        elif len(self.capteurs_connectes) < 4:
            self.log(f"⏳ En attente... {len(self.capteurs_connectes)}/4 capteurs connectés")
    
    def demarrer_jeu(self):
        """Démarrer une nouvelle partie"""
        self.log("🎮 === DÉBUT DE PARTIE ===")
        self.jeu_en_cours = True
        self.round_actuel = 0
        self.temperatures_recues = {cid: [] for cid in self.capteurs_connectes.keys()}
        self.votes_recus = {}
        
        # Choisir l'espion aléatoirement
        capteurs_ids = list(self.capteurs_connectes.keys())
        self.espion_choisi = random.choice(capteurs_ids)
        
        self.log(f"🕵️ Espion choisi: {self.espion_choisi}")
        
        # Attribuer les rôles
        for capteur_id in capteurs_ids:
            if capteur_id == self.espion_choisi:
                role = "espion"
                self.capteurs_connectes[capteur_id]["role"] = "espion"
            else:
                role = "normal"
                self.capteurs_connectes[capteur_id]["role"] = "normal"
            
            # Publier le rôle
            self.client.publish(f"iot/role/{capteur_id}", role, qos=1)
            self.log(f"📤 Rôle envoyé à {capteur_id}: {role}")
        
        # Publier le début de jeu
        info_jeu = {
            "status": "started",
            "nb_capteurs": len(capteurs_ids),
            "max_rounds": self.max_rounds,
            "message": "🚀 Le jeu commence ! Envoyez vos températures."
        }
        
        self.client.publish("iot/game/status", json.dumps(info_jeu), qos=1)
        self.log("📢 Signal de début de jeu envoyé à tous les capteurs")
    
    def gerer_temperature(self, capteur_id, temperature):
        """Gérer la réception d'une température"""
        if not self.jeu_en_cours:
            self.log(f"⚠️  Température reçue de {capteur_id} mais jeu non démarré")
            return
        
        if capteur_id not in self.temperatures_recues:
            self.log(f"⚠️  Température reçue de capteur inconnu: {capteur_id}")
            return
        
        # Ajouter la température
        self.temperatures_recues[capteur_id].append(temperature)
        nb_temps = len(self.temperatures_recues[capteur_id])
        
        role = self.capteurs_connectes[capteur_id].get("role", "unknown")
        self.log(f"🌡️  Température #{nb_temps} de {capteur_id} ({role}): {temperature}°C")
        
        # Vérifier si tous les capteurs ont envoyé leur température pour ce round
        self.verifier_fin_round()
    
    def verifier_fin_round(self):
        """Vérifier si le round actuel est terminé"""
        # Compter combien de capteurs ont envoyé une température pour ce round
        round_actuel = min([len(temps) for temps in self.temperatures_recues.values()])
        
        if round_actuel > self.round_actuel:
            self.round_actuel = round_actuel
            self.log(f"📊 Round {self.round_actuel}/{self.max_rounds} terminé")
            
            # Afficher un résumé du round
            self.afficher_resume_round()
            
            if self.round_actuel >= self.max_rounds:
                self.terminer_phase_temperatures()
    
    def afficher_resume_round(self):
        """Afficher un résumé du round actuel"""
        self.log(f"--- Résumé Round {self.round_actuel} ---")
        for capteur_id, temperatures in self.temperatures_recues.items():
            if len(temperatures) >= self.round_actuel:
                temp = temperatures[self.round_actuel - 1]
                role = self.capteurs_connectes[capteur_id]["role"]
                self.log(f"  {capteur_id} ({role}): {temp}°C")
        self.log("--- Fin résumé ---")
    
    def terminer_phase_temperatures(self):
        """Terminer la phase de collecte des températures"""
        self.log("🗳️  === PHASE DE VOTE ===")
        
        # Publier la fin de la phase températures
        vote_info = {
            "status": "vote_phase",
            "message": "⏰ Phase températures terminée. Votez pour l'espion !",
            "deadline": 30  # 30 secondes pour voter
        }
        
        self.client.publish("iot/game/vote", json.dumps(vote_info), qos=1)
        self.log("📢 Phase de vote démarrée - 30 secondes")
        
        # Démarrer un timer pour la fin des votes
        timer = threading.Timer(30.0, self.terminer_votes)
        timer.start()
    
    def gerer_vote(self, voteur_id, vote_pour):
        """Gérer un vote reçu"""
        if voteur_id not in self.capteurs_connectes:
            self.log(f"⚠️  Vote reçu de capteur inconnu: {voteur_id}")
            return
        
        self.votes_recus[voteur_id] = vote_pour
        self.log(f"🗳️  Vote de {voteur_id}: accuse {vote_pour}")
        
        # Vérifier si tous ont voté
        if len(self.votes_recus) == len(self.capteurs_connectes):
            self.log("📊 Tous les votes reçus - Calcul des résultats...")
            self.terminer_votes()
    
    def terminer_votes(self):
        """Terminer la phase de vote et calculer les résultats"""
        self.log("🏁 === CALCUL DES RÉSULTATS ===")
        
        # Compter les votes
        compteur_votes = {}
        for voteur, accuse in self.votes_recus.items():
            compteur_votes[accuse] = compteur_votes.get(accuse, 0) + 1
        
        # Trouver le plus accusé
        if compteur_votes:
            plus_accuse = max(compteur_votes, key=compteur_votes.get)
            nb_votes_max = compteur_votes[plus_accuse]
        else:
            plus_accuse = None
            nb_votes_max = 0
        
        # Déterminer le gagnant
        if plus_accuse == self.espion_choisi:
            gagnant = "CAPTEURS"
            message = f"🎉 Les capteurs gagnent ! Espion {self.espion_choisi} démasqué avec {nb_votes_max} votes."
        else:
            gagnant = "ESPION"
            message = f"😈 L'espion gagne ! {plus_accuse or 'Personne'} accusé à tort. Vrai espion: {self.espion_choisi}"
        
        self.log(f"🏆 Gagnant: {gagnant}")
        self.log(message)
        
        # Publier les résultats
        resultats = {
            "gagnant": gagnant,
            "espion_reel": self.espion_choisi,
            "plus_accuse": plus_accuse,
            "votes": compteur_votes,
            "message": message,
            "details_temperatures": self.temperatures_recues
        }
        
        self.client.publish("iot/resultats", json.dumps(resultats, ensure_ascii=False), qos=1)
        self.log("📤 Résultats publiés")
        
        # Réinitialiser pour une nouvelle partie
        self.reinitialiser_jeu()
    
    def gerer_ping(self, capteur_id):
        """Répondre à un ping de capteur"""
        self.client.publish(f"iot/pong/{capteur_id}", "alive", qos=1)
        if capteur_id in self.capteurs_connectes:
            self.capteurs_connectes[capteur_id]["derniere_activite"] = datetime.now()
    
    def reinitialiser_jeu(self):
        """Réinitialiser pour une nouvelle partie"""
        self.log("🔄 Réinitialisation pour nouvelle partie dans 10 secondes...")
        
        def nouvelle_partie():
            time.sleep(10)
            if len(self.capteurs_connectes) == 4:
                self.demarrer_jeu()
            else:
                self.jeu_en_cours = False
                self.log("⏳ En attente de 4 capteurs pour nouvelle partie...")
        
        thread = threading.Thread(target=nouvelle_partie)
        thread.daemon = True
        thread.start()
    
    def demarrer_serveur(self):
        """Démarrer le serveur"""
        self.log("🚀 Démarrage du serveur arbitre...")
        
        try:
            self.client.connect(self.broker_host, self.broker_port, 60)
            self.client.loop_forever()
        except Exception as e:
            self.log(f"❌ Erreur serveur: {e}")

if __name__ == "__main__":
    # Configuration
    BROKER_IP = "10.109.150.194"  # Remplacez par votre IP Windows
    
    print("🎮 === SERVEUR ARBITRE - JEU DISTRIBUTIF ===")
    print(f"📡 Broker MQTT: {BROKER_IP}:1883")
    print("⏳ Démarrage...")
    
    serveur = ServeurArbitre(broker_host=BROKER_IP)
    
    try:
        serveur.demarrer_serveur()
    except KeyboardInterrupt:
        print("\n🛑 Arrêt du serveur demandé...")
        serveur.client.disconnect()