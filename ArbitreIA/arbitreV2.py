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

        # === ÉTAT DU JEU ===
        self.capteurs_connectes = {}   # {id: True}
        self.espion = None             # id de l'espion
        self.jeu_actif = False

        # Une seule température attendue par capteur pour ce scénario
        self.temperatures = {}         # {id: {"ville": str, "temperature": float}}
        self.villes_attribuees = {}    # {id: "Ville"}

        # Villes candidates (tu peux en ajouter)
        self.pool_villes = [
            "Paris", "Lyon", "Marseille", "Toulouse", "Lille",
            "Bordeaux", "Nantes", "Nice", "Montpellier", "Strasbourg"
        ]

        # MQTT
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, "serveur")
        self.client.on_connect = self.quand_connecte
        self.client.on_message = self.quand_message_recu

        # Timer de sécurité si tous n’envoient pas la température
        self.timer_fin_manche = None

    def afficher(self, message):
        heure = time.strftime("%H:%M:%S")
        print(f"[{heure}] {message}")

    # ===================== MQTT =====================

    def quand_connecte(self, client, userdata, flags, rc):
        if rc == 0:
            self.afficher("✅ Serveur connecté au broker MQTT")
            client.subscribe("iot/connexion/+")
            client.subscribe("iot/temperature/+")
            self.afficher("📡 En attente des capteurs...")
        else:
            self.afficher(f"❌ Erreur de connexion rc={rc}")

    def quand_message_recu(self, client, userdata, msg):
        try:
            topic = msg.topic
            payload = msg.payload.decode("utf-8")

            # Connexion d'un capteur
            if topic.startswith("iot/connexion/"):
                capteur_id = topic.split("/")[-1]
                self.nouveau_capteur(capteur_id)

            # Une température reçue
            elif topic.startswith("iot/temperature/"):
                capteur_id = topic.split("/")[-1]
                self.reception_temperature(capteur_id, payload)

        except Exception as e:
            self.afficher(f"❌ Erreur traitement message: {e}")

    # ===================== LOGIQUE DE JEU =====================

    def nouveau_capteur(self, capteur_id):
        self.afficher(f"🔌 Nouveau capteur: {capteur_id}")
        self.capteurs_connectes[capteur_id] = True

        nb = len(self.capteurs_connectes)
        if nb < 4:
            self.afficher(f"⏳ {nb}/4 capteurs connectés")
        elif nb == 4 and not self.jeu_actif:
            # Attendre 1 seconde pour laisser tous s’abonner à leurs topics
            threading.Timer(1.0, self.demarrer_jeu).start()
        else:
            self.afficher(f"ℹ️ Déjà 4 capteurs. Ignoré: {capteur_id}")

    def demarrer_jeu(self):
        if len(self.capteurs_connectes) < 4:
            return

        self.afficher("🎮 === DÉBUT DE PARTIE ===")
        self.jeu_actif = True
        self.temperatures.clear()
        self.villes_attribuees.clear()

        # Choisir l'espion
        ids = list(self.capteurs_connectes.keys())
        self.espion = random.choice(ids)
        self.afficher(f"🕵️ Espion secret: {self.espion}")

        # Attribuer 4 villes distinctes
        villes = random.sample(self.pool_villes, 4)
        for i, capteur_id in enumerate(ids):
            # 1) Envoyer le rôle individuel
            role = "espion" if capteur_id == self.espion else "normal"
            self.client.publish(f"iot/role/{capteur_id}", role, qos=1, retain=False)
            self.afficher(f"📤 Rôle envoyé à {capteur_id}: {role}")

            # 2) Envoyer la ville juste après le rôle
            ville = villes[i]
            self.villes_attribuees[capteur_id] = ville
            # petite latence pour s'assurer que le client a traité le rôle
            time.sleep(0.1)
            self.client.publish(f"iot/ville/{capteur_id}", ville, qos=1, retain=False)
            self.afficher(f"🗺️ Ville envoyée à {capteur_id}: {ville}")

        # Message global d’instruction (facultatif)
        self.client.publish("iot/demande", "Envoyez 1 température pour votre ville.", qos=0)

        # Démarrer un timer de sécurité (ex: 25 s) si tous n’envoient pas
        self.timer_fin_manche = threading.Timer(25.0, self.cloturer_si_incomplet)
        self.timer_fin_manche.start()

    def reception_temperature(self, capteur_id, payload):
        if not self.jeu_actif or capteur_id not in self.capteurs_connectes:
            return

        # Accepter JSON {"ville","lat","lon","temperature"} ou un float brut
        ville = self.villes_attribuees.get(capteur_id, None)
        temperature = None
        try:
            # Essayons JSON d’abord
            data = json.loads(payload)
            if isinstance(data, dict) and "temperature" in data:
                temperature = float(data["temperature"])
                ville = data.get("ville", ville)
            else:
                # si ce n’est pas un dict exploitable, tentative float
                temperature = float(payload)
        except Exception:
            # Pas du JSON → peut-être un float brut
            try:
                temperature = float(payload)
            except Exception:
                self.afficher(f"⚠️ Payload température invalide de {capteur_id}: {payload}")
                return

        self.temperatures[capteur_id] = {"ville": ville, "temperature": temperature}
        self.afficher(f"🌡️ {capteur_id} ({ville}) -> {temperature}°C")
        
        # Vérifier si on a 4 températures
        if len(self.temperatures) == 4:
            # Stopper timer de sécurité
            if self.timer_fin_manche:
                self.timer_fin_manche.cancel()
                self.timer_fin_manche = None
            self.evaluer_manche()

    def cloturer_si_incomplet(self):
        # Appelé si tous n’ont pas répondu à temps
        manquants = set(self.capteurs_connectes.keys()) - set(self.temperatures.keys())
        if manquants and self.jeu_actif:
            self.afficher(f"⏰ Temps écoulé. Manquants: {', '.join(manquants)}")
            # On continue avec ce qu’on a (si < 3 mesures, on annule)
            if len(self.temperatures) >= 3:
                self.evaluer_manche()
            else:
                self.afficher("❌ Trop peu de mesures. Annulation de la manche.")
                self.fin_manche(gagnant="AUCUN", accuse=None)

    def evaluer_manche(self):
        """
        On accuse automatiquement le capteur dont la valeur s'écarte le plus des autres.
        Méthode simple et robuste: on utilise la médiane comme référence,
        puis on prend le plus grand écart absolu à cette médiane.
        """
        valeurs = []
        for cid, info in self.temperatures.items():
            valeurs.append((cid, info["temperature"]))

        med = median([v for _, v in valeurs])
        # calcul des écarts absolus
        ecarts = [(cid, abs(temp - med)) for cid, temp in valeurs]
        ecarts.sort(key=lambda x: x[1], reverse=True)
        accuse_id, ecart_max = ecarts[0]

        self.afficher("📊 Récap des températures:")
        for cid, info in self.temperatures.items():
            self.afficher(f"   - {cid} @ {info['ville']}: {info['temperature']}°C")

        self.afficher(f"🔍 Médiane: {med:.2f}°C | Accusé auto: {accuse_id} (écart {ecart_max:.2f})")

        if accuse_id == self.espion:
            gagnant = "CAPTEURS"
            self.afficher(f"🎉 LES CAPTEURS GAGNENT ! Espion démasqué: {self.espion}")
        else:
            gagnant = "ESPION"
            self.afficher(f"😈 L'ESPION GAGNE ! Accusé à tort: {accuse_id}. Vrai espion: {self.espion}")

        self.fin_manche(gagnant=gagnant, accuse=accuse_id)

    def fin_manche(self, gagnant, accuse):
        # Publier les résultats détaillés
        resultats = {
            "gagnant": gagnant,
            "espion": self.espion,
            "accuse": accuse,
            "temperatures": self.temperatures,
            "villes": self.villes_attribuees
        }
        self.client.publish("iot/resultats", json.dumps(resultats, ensure_ascii=False), qos=1)
        self.afficher("📤 Résultats publiés")

        # Préparer la prochaine partie
        self.jeu_actif = False
        self.temperatures.clear()
        self.villes_attribuees.clear()
        self.afficher("🔄 Nouvelle partie dans 10 secondes...")
        threading.Timer(30.0, self.demarrer_jeu).start()

    # ===================== DÉMARRAGE =====================

    def demarrer_serveur(self):
        self.afficher("🚀 Démarrage du serveur...")
        try:
            self.client.connect(self.broker_ip, 1883, 60)
            self.client.loop_forever()
        except Exception as e:
            self.afficher(f"❌ Erreur: {e}")

# === MAIN ===
if __name__ == "__main__":
    MON_IP_BROKER = "10.109.150.194"  # adapte avec l’IP de ton broker
    print("🎮 === SERVEUR DE JEU IoT (Rôles + Villes + Détection auto) ===")
    print(f"📡 Broker: {MON_IP_BROKER}")
    print("📋 Règles: 4 capteurs -> rôle -> ville -> 1 température -> verdict")
    print("⏳ Démarrage...\n")

    serveur = ServeurArbitre(MON_IP_BROKER)
    try:
        serveur.demarrer_serveur()
    except KeyboardInterrupt:
        print("\n🛑 Arrêt du serveur")
