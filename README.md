# Lumina

**Récupération de données pour Windows — interface rétro Windows 98, moteur moderne.**

Lumina retrouve vos fichiers perdus sur disques durs, SSD, clés USB et cartes SD. Pas de résultats inventés : chaque fichier affiché provient d'une vraie analyse de votre disque.

---

## Ce que Lumina fait

- **Quick Scan** — lit les métadonnées NTFS (MFT) en quelques secondes pour retrouver les fichiers supprimés récemment.
- **Deep Scan** — analyse secteur par secteur pour récupérer JPEG, PNG, PDF, ZIP, DOCX, MP4, MOV, SQLite et bien d'autres.
- **Scanner natif Rust** — jusqu'à 300 MB/s sur les images disque locales, 84× plus rapide que le chemin Python.
- **Sécurité de récupération** — bloque toute écriture vers le volume source et guide vers un dossier sûr.
- **Rapports DFXML + SHA-256** — export forensique complet avec hash d'intégrité après extraction.

## Démarrage rapide

```powershell
# Construire l'exécutable
python -m PyInstaller lumina.spec --noconfirm

# Lancer (droits Administrateur requis)
dist\Lumina.exe
```

Au premier lancement, un assistant de configuration s'ouvre : langue, dossier de récupération, moteur de scan, et avertissement de sécurité obligatoire.

## Points à savoir avant de lancer

- Ne jamais récupérer vers le disque source.
- SSD + TRIM actif = les données effacées peuvent être irrécupérables.
- Pour les supports endommagés : créez d'abord une image disque, scannez l'image.
- Extraction limitée à 500 Mo par fichier (signalé dans l'interface et le rapport DFXML).
- Windows uniquement — accès raw disk et UAC obligatoires.

## Ce qui arrive ensuite

- Parseurs ext4 / APFS pour un Quick Scan Linux et macOS.
- Scanner Rust étendu aux lecteurs physiques (`\\.\PhysicalDrive`).
- Pipeline CI/CD avec release automatique de `Lumina.exe`.
