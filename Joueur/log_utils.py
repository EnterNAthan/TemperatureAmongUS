"""Utilitaires simples de logging pour le projet.

Fournit des fonctions légères pour afficher des messages horodatés,
des séparateurs visuels et des sections pour regrouper les logs.
Ce module reste volontairement minimal (utilise print) pour rester
compatible avec l'exécution sur Raspberry / systèmes sans configuration
de logging avancée.
"""
from __future__ import annotations
import time
from typing import Optional


def _ts() -> str:
    return time.strftime("%H:%M:%S")


def info(msg: str, id: Optional[str] = None) -> None:
    """Affiche un message horodaté. Si id est fourni, l'ajoute entre crochets."""
    prefix = f"[{_ts()}]"
    if id:
        prefix += f" [{id}]"
    print(f"{prefix} {msg}")


def sep(char: str = "=", width: int = 70) -> None:
    """Affiche une ligne de séparation composée du caractère donné."""
    print(char * width)


def section(title: str, char: str = "=", width: int = 70) -> None:
    """Affiche une section avec séparateurs avant/après et un titre horodaté.

    Exemple visuel pour séparer deux grosses étapes.
    """
    sep(char, width)
    print(f"[{_ts()}] {title}")
    sep(char, width)


def group(title: str, lines: list[str], id: Optional[str] = None) -> None:
    """Affiche un petit groupe de lignes sous un même titre.

    Utilisé pour regrouper des logs relatifs à une même étape.
    """
    section(title)
    for l in lines:
        info(l, id=id)
    sep()



            # prompt += "Reponds uniquement en JSON avec le champ 'espion_presume' contenant l'ID du capteur suspect (ex: {\"espion_presume\": \"bot\"}). Ne fournis aucun texte hors du JSON."