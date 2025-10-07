# Automated Impostor Analyzer Game with Ollama AI and Raspberry Pi

This project is an automated game where Raspberry Pi players debate with an AI arbitrator that acts as an impostor analyzer. The AI uses GPT-20B and Gemma 3B models hosted on an Ollama server. Communication between players and the server is handled via MQTT, with real-time interactions shown in a graphical interface.

---

## Features

- **AI Impostor Analyzer**: Uses powerful GPT-20B and Gemma 3B models to analyze player behavior and detect inconsistencies.
- **Raspberry Pi Players**: Each player is represented by a Raspberry Pi running a client that interacts with the AI.
- **MQTT Communication**: Lightweight and efficient communication protocol between clients and the AI server.
- **Graphical Interface**: Provides real-time updates of debates, arguments, and AI analysis.
- **Ollama Server Integration**: Hosts AI models and processes requests from players.

---

## Architecture

1. **Ollama Server**: Hosts GPT-20B and Gemma 3B models.
2. **Raspberry Pi Clients**: Players who interact with the AI and each other.
3. **MQTT Broker**: Facilitates real-time communication.
4. **Graphical Interface**: Visualizes debates and AI decision-making.

---

## Installation

### Prerequisites

- Raspberry Pi with Python 3.x
- MQTT Broker (e.g., Mosquitto)
- Access to Ollama server hosting GPT-20B and Gemma 3B models
- Python libraries: `paho-mqtt`, `tkinter`, `requests`, etc.

### Setup
#### Sur le rasberry 
```bash
git clone https://github.com/EnterNathan/TemperatureAmongUS.git
source env/bin/activate
python joueur.py <PSeudo de votre Joueur>
```
#### Sur l'arbitre (un pc de votre choix meme réseau)
```bash
git clone https://github.com/EnterNathan/TemperatureAmongUS.git
source env/bin/activate
python display_arbitre
```

python joueur.py <PSeudo de votre Joueur>
```
