#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import paho.mqtt.client as mqtt
import json
import random
import time
import threading
from statistics import median


class ServeurArbitre:
    def __init__(self, broker_ip):
        self.broker_ip = broker_ip
        # État du jeu
        #Liste les capteur connecter
        self.capteurs_connectes = {}    
        #ID de l'espion
        self.espion = None              
        #Jeux actif ou non 
        self.jeu_actif = False        
        # Données de la partie
        self.temperatures = {}          # Températures reçues {id: {ville, temperature}}
        self.villes_attribuees = {}     # Villes assignées à chaque capteur
        
        # Liste des villes possibles
        self.pool_villes = [
            "Chambery", "Vassieux-en-Vercors", "Annecy", "Genève", "Lyon"
        ]
        
        # Configuration MQTT
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, "serveur")
        self.client.on_connect = self.quand_connecte
        self.client.on_message = self.quand_message_recu
        
        # Timer de sécurité
        self.timer_fin_manche = None

    def afficher(self, message):
        """Affichage avec horodatage"""
        heure = time.strftime("%H:%M:%S")
        print(f"[{heure}] {message}")

    # ===== GESTION MQTT =====
        
    def quand_connecte(self, client, userdata, flags, rc):
        """Callback quand le serveur se connecte au broker"""
        if rc == 0:
            self.afficher("[OK] Serveur connecte au broker MQTT")
            # S'abonner aux topics importants
            #Topic pour géré la connexion et les joueurs connecter
            client.subscribe("iot/connexion/+")
            #Topic pour recevoir les temperature des capteurs
            client.subscribe("iot/temperature/+")
            self.afficher("[INFO] En attente des capteurs...")
        else:
            self.afficher(f"[ERREUR] Connexion refusee rc={rc}")

    def quand_message_recu(self, client, userdata, msg):
        """Callback quand un message MQTT arrive"""
        try:
            topic = msg.topic
            payload = msg.payload.decode("utf-8")
            
            # Un capteur se connecte : iot/connexion/Nathan
            if topic.startswith("iot/connexion/"):
                capteur_id = topic.split("/")[-1]  # Récupère le pseudo la  "Nathan"
                self.nouveau_capteur(capteur_id)
            
            # Une température arrive : iot/temperature/Nathan
            elif topic.startswith("iot/temperature/"):
                capteur_id = topic.split("/")[-1]
                self.reception_temperature(capteur_id, payload)
                
        except Exception as e:
            self.afficher(f"[ERREUR] Traitement message: {e}")

    # ===== LOGIQUE DE JEU =====
    
    def nouveau_capteur(self, capteur_id):
        """Quand un nouveau capteur se connecte"""
        self.afficher(f"[CONNEXION] Nouveau capteur: {capteur_id}")
        self.capteurs_connectes[capteur_id] = True
        
        nb_capteurs = len(self.capteurs_connectes)
        # Attente des 4 Joueurs
        if nb_capteurs < 4:
            self.afficher(f"[ATTENTE] {nb_capteurs}/4 capteurs connectes")
        elif nb_capteurs == 4 and not self.jeu_actif:
            # On a 4 capteurs, on démarre dans 1 seconde
            self.afficher("[JEU] 4 capteurs connectes! Demarrage...")
            threading.Timer(1.0, self.demarrer_jeu).start()
            
            
    # Lancer une nouvelle partie
    def demarrer_jeu(self):
        """Lance une nouvelle partie"""
        if len(self.capteurs_connectes) < 4:
            return
            
        self.afficher("=== DEBUT DE PARTIE ===")
        self.jeu_actif = True
        self.temperatures.clear()
        self.villes_attribuees.clear()
        
        # 1. Choisir l'espion au hasard
        ids_capteurs = list(self.capteurs_connectes.keys())
        self.espion = random.choice(ids_capteurs)
        self.afficher(f"[ESPION] Espion secret: {self.espion}")
        
        # 2. Attribuer une ville différente à chaque capteur
        villes_choisies = random.sample(self.pool_villes, 4)
        
        for i, capteur_id in enumerate(ids_capteurs):
            # Envoyer le rôle (espion ou normal)
            role = "espion" if capteur_id == self.espion else "normal"
            # On publie dans le channel rôle 
            self.client.publish(f"iot/role/{capteur_id}", role, qos=1)
            #Affichage du role
            self.afficher(f"[ROLE] {capteur_id}: {role}")
            
            # Envoyer la ville
            ville = villes_choisies[i]
            self.villes_attribuees[capteur_id] = ville
            #pause pour lisibilité
            time.sleep(0.5)  
            self.client.publish(f"iot/ville/{capteur_id}", ville, qos=1)
            self.afficher(f"[VILLE] {capteur_id}: {ville}")
        
        # 3. Demander les températures
        self.client.publish("iot/demande", "Envoyez la temperature de votre ville", qos=0)
        
        # 4. créer un timer avec un thread de sécurité
        self.timer_fin_manche = threading.Timer(25.0, self.cloturer_si_incomplet)
        self.timer_fin_manche.start()

    def reception_temperature(self, capteur_id, payload):
        """Quand on reçoit une température d'un capteur"""
        # Ignorer si le jeu n'est pas actif ou capteur inconnu
        if not self.jeu_actif or capteur_id not in self.capteurs_connectes:
            return
            
        # Extraire la température du message (JSON ou nombre simple)
        ville = self.villes_attribuees.get(capteur_id, "Inconnue")
        temperature = None
        
        try:
            # Essayer de parser en JSON
            data = json.loads(payload)
            if isinstance(data, dict) and "temperature" in data:
                temperature = float(data["temperature"])
                ville = data.get("ville", ville)
            else:
                temperature = float(payload)
        except:
            # Pas du JSON, essayer un nombre simple
            try:
                temperature = float(payload)
            except:
                self.afficher(f"[ERREUR] Temperature invalide de {capteur_id}: {payload}")
                return
        
        # Stocker la température
        self.temperatures[capteur_id] = {"ville": ville, "temperature": temperature}
        self.afficher(f"[TEMP] {capteur_id} ({ville}): {temperature}°C")
        
        # Si on a 4 températures, on peut évaluer
        if len(self.temperatures) == 4:
            if self.timer_fin_manche:
                self.timer_fin_manche.cancel()
            self.evaluer_manche()
            
    # Permet de cloturer la manche si il y'a pas de réponse
    def cloturer_si_incomplet(self):    
        """Si tous les capteurs n'ont pas répondu à temps"""
        manquants = set(self.capteurs_connectes.keys()) - set(self.temperatures.keys())
        if manquants and self.jeu_actif:
            self.afficher(f"[TIMEOUT] Capteurs manquants: {', '.join(manquants)}")
            if len(self.temperatures) >= 3:
                self.evaluer_manche()
            else:
                self.afficher("[ANNULATION] Pas assez de temperatures")
                self.fin_manche("AUCUN", None)

    def evaluer_manche(self):
        """Détermine qui gagne en analysant les températures"""
        # Récupérer toutes les températures
        valeurs = []
        for capteur_id, info in self.temperatures.items():
            valeurs.append((capteur_id, info["temperature"]))
        
        # Calculer la médiane (valeur du milieu)
        temperatures_seules = [temp for _, temp in valeurs]
        mediane = median(temperatures_seules)
        
        # Trouver qui s'écarte le plus de la médiane
        ecarts = []
        for capteur_id, temp in valeurs:
            ecart = abs(temp - mediane)
            ecarts.append((capteur_id, ecart))
        
        # Trier par écart décroissant
        ecarts.sort(key=lambda x: x[1], reverse=True)
        accuse_id, ecart_max = ecarts[0]  # Le plus suspect
        
        # Afficher les résultats
        self.afficher("[ANALYSE] Temperatures recues:")
        for capteur_id, info in self.temperatures.items():
            self.afficher(f"  - {capteur_id} ({info['ville']}): {info['temperature']}°C")
        
        self.afficher(f"[VERDICT] Mediane: {mediane:.1f}°C")
        self.afficher(f"[VERDICT] Accuse: {accuse_id} (ecart: {ecart_max:.1f}°C)")
        
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
            "temperatures": self.temperatures,
            "villes": self.villes_attribuees
        }
        self.client.publish("iot/resultats", json.dumps(resultats, ensure_ascii=False), qos=1)
        self.afficher("[PUBLICATION] Resultats publies")
        
        # Réinitialiser pour la prochaine partie
        self.jeu_actif = False
        self.temperatures.clear()
        self.villes_attribuees.clear()
        
        # Programmer la prochaine partie
        self.afficher("[INFO] Prochaine partie dans 30 secondes...")
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
    
    print("=== SERVEUR DE JEU IoT ===")
    print(f"Broker: {IP_BROKER}")
    print("Regles: 4 capteurs -> attribution roles/villes -> temperatures -> verdict")
    print("Demarrage...\n")
    
    serveur = ServeurArbitre(IP_BROKER)
    try:
        serveur.demarrer_serveur()
    except KeyboardInterrupt:
        print("\nArret du serveur")
