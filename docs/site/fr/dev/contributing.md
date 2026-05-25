---
title: Contribution
description: Configuration du développement, style de code, signature DCO et workflow des pull requests pour les contributeurs de HistorySync.
---

# Contribuer à HistorySync

Merci de votre intérêt pour la contribution ! Les corrections de bugs, les nouveaux extracteurs de navigateurs, les améliorations de documentation, les traductions et la couverture de tests sont particulièrement bienvenus.

---

## Pour Commencer

1. **Parcourez les [Issues](https://github.com/TheSkyC/HistorySync/issues) ouvertes** — recherchez des labels comme `good first issue` ou `help wanted`.
2. **Commentez sur un problème** avant de commencer un travail significatif pour éviter les efforts en double.
3. Pour les petites corrections (fautes de frappe, bugs d'une ligne), ouvrez directement une PR sans problème préalable.

---

## Configuration du Développement

### Prérequis

| Outil | Version requise |
|---|---|
| Python | **3.12** recommandé (correspond à l'environnement CI) |
| Git | N'importe quelle version récente |

> HistorySync prend en charge Python 3.10+, mais utilisez **3.12** lors de vos contributions pour que votre environnement corresponde au linting, aux tests et aux dépendances verrouillées.

### Étapes

```bash
# 1. Forkez le dépôt sur GitHub, puis clonez votre fork
git clone https://github.com/YOUR_USERNAME/HistorySync.git
cd HistorySync

# 2. Créer et activer un environnement virtuel
python -m venv venv
source venv/bin/activate     # macOS / Linux
.\venv\Scripts\activate      # Windows

# 3. Installer les dépendances d'exécution
pip install -r requirements.txt

# 4. Installer les dépendances de développement et de test
pip install -r requirements-dev.txt
pip install -r requirements-test.txt

# 5. (Recommandé) Installer les hooks pre-commit
pre-commit install

# 6. Vérifier la configuration
python -m src.main --fresh
```

---

## Style de Code

Ce projet utilise **[Ruff](https://github.com/astral-sh/ruff)** pour le linting et le formatage. La configuration se trouve dans `ruff.toml`.

```bash
# Vérifier les problèmes
ruff check .

# Corriger automatiquement où possible
ruff check . --fix

# Formater le code
ruff format .

# Exécuter tous les hooks pre-commit manuellement
pre-commit run --all-files
```

**Notes générales sur le style :**

- Suivez les patterns existants dans le fichier que vous modifiez.
- Gardez le code GUI (PySide6) et la logique métier **strictement séparés** — les services ne doivent pas importer Qt.
- Préférez la clarté à l'ingéniosité.
- Ajoutez ou mettez à jour les docstrings lorsque vous modifiez les APIs publiques.

---

## Exécution des Tests

```bash
# Exécuter la suite de tests complète
pytest

# Exécuter un fichier de test spécifique
pytest tests/test_chromium_extractor.py

# Sortie détaillée
pytest -v

# Avec couverture (nécessite pytest-cov, inclus dans requirements-test.txt)
pytest --cov=src --cov-report=term-missing

# Mêmes vérifications de lint que la CI
ruff check src/ tests/
ruff format --check src/ tests/
```

Tous les tests doivent passer avant qu'une PR puisse être fusionnée. Si vous ajoutez de nouvelles fonctionnalités, veuillez inclure les tests correspondants.

---

## Directives pour les Commits

Utilisez des messages de commit clairs et impératifs :

```
<type>(<scope>): <sujet>
```

**Exemples :**
```
fix(extractor): handle missing WAL file during Chromium extraction
feat(browser): add Arc browser support on macOS
docs(webdav): document merge behaviour
test(search): add unit tests for query DSL parser
chore(dev): update Ruff to 0.15
```

**Types :** `fix`, `feat`, `refactor`, `docs`, `test`, `chore`, `perf`, `style`, `ci`, `build`

**Règles :**
- Ligne de sujet ≤ 72 caractères.
- Utilisez un verbe impératif en minuscules (`add`, `fix`, `remove` — pas `added`, `fixes`).
- Ajoutez un corps pour expliquer le *pourquoi* des changements non évidents.

---

## Certificat d'Origine du Développeur (DCO)

**Chaque commit doit être signé. Les PRs avec des commits non signés ne seront pas fusionnées.**

```bash
git commit -s -m "fix: handle missing WAL file"
# Ajoute : Signed-off-by: Votre Nom <votre@email.com>
```

Assurez-vous que votre identité Git est configurée :
```bash
git config --global user.name "Votre Nom"
git config --global user.email "votre@email.com"
```

### Vous avez oublié de signer ?

```bash
# Dernier commit uniquement
git commit --amend --no-edit --signoff
git push --force-with-lease

# Plusieurs commits (les N derniers)
git rebase --signoff HEAD~N
git push --force-with-lease
```

---

## Workflow des Pull Requests

1. **Créez une branche** depuis `main` :
   ```bash
   git checkout -b fix/edge-history-extraction-utf8
   git checkout -b feat/opera-browser-support
   git checkout -b docs/webdav-setup-guide
   ```

2. **Effectuez vos modifications** — gardez les commits ciblés et atomiques.

3. **Exécutez les tests et le lint** localement.

4. **Pushez et ouvrez une PR** contre `main` :
   ```bash
   git push origin your-branch-name
   ```

5. Suivez les règles de PR :
   - Un changement ou un ensemble de changements liés par PR.
   - Description claire de *ce* qui a changé et *pourquoi*.
   - Liez le problème associé avec `Closes #123`.
   - Ajoutez des captures d'écran / enregistrements pour les changements UI.
   - Chaque commit doit être signé.

6. **Répondez rapidement aux retours de révision**.

---

## Ce Que Nous Recherchons

**Particulièrement bienvenus :**

- **Nouveaux extracteurs de navigateurs** — prise en charge de forks Chromium/Firefox supplémentaires.
- **Corrections de bugs** — notamment les problèmes spécifiques aux plateformes (chemins macOS, permissions Linux, UAC Windows).
- **Améliorations des performances** — optimisation des requêtes, vitesse d'extraction, utilisation de la mémoire.
- **Améliorations UI/UX** — accessibilité, navigation au clavier, cohérence des thèmes.
- **Couverture de tests** — nouveaux tests pour les chemins de code actuellement non testés.
- **Documentation** — améliorer ce site, ajouter des docstrings inline, corriger les fautes de frappe.
- **Traductions** — mises à jour des fichiers `.po` dans `src/resources/locales/`.

**Discutez d'abord (ouvrez un problème avant de coder) :**

- Modifications architecturales majeures.
- Nouvelles dépendances tierces.
- Modifications du protocole de synchronisation WebDAV ou du schéma de base de données.

---

## Failles de Sécurité

**N'ouvrez pas de problème public pour les failles de sécurité.**

Signalez-les en privé en envoyant un e-mail à **security@historysync.app**. Incluez une description, les étapes de reproduction et l'impact potentiel. Vous recevrez une réponse dans les 72 heures.

---

## Licence

En soumettant une pull request, vous acceptez que votre contribution soit licenciée sous **Apache 2.0** et vous certifiez le DCO pour chaque commit.
