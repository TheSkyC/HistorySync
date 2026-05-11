---
title: Raccourcis Clavier
description: Les 25 raccourcis clavier configurables de HistorySync — un raccourci global et 24 raccourcis dans l'application.
---

# Raccourcis Clavier

HistorySync propose **25 raccourcis configurables** — un raccourci global et 24 raccourcis dans l'application. Tous peuvent être modifiés dans **Paramètres → Raccourcis Clavier**.

---

## Raccourci Global

Ce raccourci fonctionne à l'échelle du système — il se déclenche même lorsque HistorySync est en arrière-plan ou réduit dans la barre des tâches.

| Action | Défaut | Remarques |
|---|---|---|
| **Ouvrir la Superposition d'Accès Rapide** | <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>H</kbd> | Affiche / masque la superposition de recherche de style Spotlight |

!!! info "Linux / Wayland"
    Les raccourcis globaux via `pynput` ne sont **pas pris en charge sur Wayland**. Utilisez `--quick` avec une liaison de touches au niveau système comme solution de contournement :
    ```bash
    # Liez cette commande à un raccourci système dans les paramètres de votre DE
    python -m src.main --quick
    ```

!!! info "macOS"
    La première fois que le raccourci global se déclenche, macOS demandera la permission **Accessibilité**. Accordez-la dans **Réglages Système → Confidentialité et sécurité → Accessibilité**.

---

## Raccourcis Dans l'Application

Ces raccourcis sont actifs lorsque la fenêtre HistorySync est au premier plan.

### Valeurs par défaut actuelles

| Catégorie | Raccourcis par défaut |
|---|---|
| **Navigation entre pages** | Tableau de bord <kbd>Ctrl</kbd>+<kbd>1</kbd>, Historique <kbd>Ctrl</kbd>+<kbd>2</kbd>, Signets <kbd>Ctrl</kbd>+<kbd>3</kbd>, Paramètres <kbd>Ctrl</kbd>+<kbd>4</kbd>, Journaux <kbd>Ctrl</kbd>+<kbd>5</kbd>, Statistiques <kbd>Ctrl</kbd>+<kbd>6</kbd> |
| **Actions globales** | Synchroniser maintenant <kbd>Ctrl</kbd>+<kbd>R</kbd>, Focus recherche <kbd>Ctrl</kbd>+<kbd>F</kbd> |
| **Page Historique** | Ouvrir la sélection <kbd>Entrée</kbd>, Supprimer la sélection <kbd>Suppr</kbd>, Copier l'URL <kbd>Ctrl</kbd>+<kbd>C</kbd>, Copier le titre + l'URL <kbd>Ctrl</kbd>+<kbd>Maj</kbd>+<kbd>C</kbd>, Basculer le favori <kbd>Ctrl</kbd>+<kbd>B</kbd>, Ajouter une note <kbd>Ctrl</kbd>+<kbd>N</kbd>, Ouvrir l'export <kbd>Ctrl</kbd>+<kbd>E</kbd>, Masquer la sélection non attribué par défaut |
| **Page Signets** | Ouvrir <kbd>Entrée</kbd>, Copier l'URL <kbd>Ctrl</kbd>+<kbd>C</kbd>, Supprimer <kbd>Suppr</kbd>, Ajouter une note <kbd>Ctrl</kbd>+<kbd>N</kbd>, Localiser dans l'historique <kbd>Ctrl</kbd>+<kbd>L</kbd> |
| **Page Statistiques** | Période précédente <kbd>Alt</kbd>+<kbd>Flèche gauche</kbd>, Période suivante <kbd>Alt</kbd>+<kbd>Flèche droite</kbd> |
| **Page Paramètres** | Enregistrer <kbd>Ctrl</kbd>+<kbd>S</kbd> |

La boîte de dialogue des paramètres reste la source de vérité. Les raccourcis vides sont volontairement non attribués par défaut.

---

## Personnalisation des Raccourcis

1. Allez dans **Paramètres → Raccourcis Clavier**.
2. Cliquez sur le raccourci que vous souhaitez modifier.
3. Appuyez sur la nouvelle combinaison de touches.
4. Cliquez sur **Enregistrer**.

Pour **désactiver** un raccourci, cliquez dessus et appuyez sur <kbd>Retour arrière</kbd> ou <kbd>Suppr</kbd> pour l'effacer.

!!! warning "Conflits"
    Si deux actions partagent la même combinaison de touches, celle définie en dernier l'emporte. La boîte de dialogue des paramètres affichera une icône d'avertissement pour les conflits.

---

## Raccourcis de la Superposition d'Accès Rapide

Ces raccourcis fonctionnent à l'intérieur de la superposition (le panneau `Ctrl+Shift+H`) :

| Action | Touche |
|---|---|
| **Naviguer dans les résultats** | <kbd>↑</kbd> / <kbd>↓</kbd> |
| **Ouvrir l'URL sélectionnée** | <kbd>Entrée</kbd> |
| **Ouvrir dans un nouvel onglet** (si le navigateur le prend en charge) | <kbd>Ctrl</kbd>+<kbd>Entrée</kbd> |
| **Fermer la superposition** | <kbd>Échap</kbd> |
| **Effacer la recherche** | <kbd>Ctrl</kbd>+<kbd>A</kbd> puis <kbd>Suppr</kbd> |
