# Lumina

**Récupération de données — interface rétro Windows 98, moteur moderne, multi-plateforme.**

Lumina retrouve vos fichiers perdus sur disques durs, SSD, clés USB et cartes SD. Pas de résultats inventés : chaque fichier affiché provient d'une vraie analyse de votre disque.

---

## Ce que Lumina fait

- **Quick Scan** — lit les métadonnées NTFS, FAT32, exFAT, ext4 et HFS+ en quelques secondes pour retrouver les fichiers supprimés récemment.
- **Deep Scan** — analyse secteur par secteur pour récupérer JPEG, PNG, PDF, ZIP, DOCX, MP4, MOV, SQLite et bien d'autres.
- **Scanner natif Rust** — jusqu'à 860 MB/s sur les images disque locales, 50× plus rapide que le chemin Python.
- **Réparation JPEG / MP4** — diagnostic et reconstruction des marqueurs SOI/EOI ou des atomes moov/mdat.
- **Sécurité de récupération** — bloque toute écriture vers le volume source et guide vers un dossier sûr.
- **Rapports DFXML + SHA-256** — export forensique complet avec hash d'intégrité après extraction.
- **CLI scriptable** — `lumina scan`, `list-disks`, `recover`, `info` avec sortie JSONL / CSV / DFXML.

## Démarrage rapide

### Windows

```powershell
python scripts/build.py     # builds Rust helper + dist\Lumina.exe
dist\Lumina.exe              # requires Administrator (UAC prompt)
```

### macOS

```bash
python scripts/build.py     # builds dist/Lumina.app
open dist/Lumina.app         # macOS will ask for admin elevation on first scan
# Optional ad-hoc codesign so Gatekeeper stops complaining:
codesign --deep -s - dist/Lumina.app
```

### Linux

```bash
python scripts/build.py                 # builds dist/lumina/ (one-folder)
sudo bash scripts/install_linux.sh       # installs to /opt/lumina + desktop entry
lumina                                   # run via PATH symlink
```

`scripts/build.py` automatically picks the correct PyInstaller spec
(`lumina.spec`, `lumina_macos.spec`, `lumina_linux.spec`) based on
`platform.system()`. Pass `--skip-rust` to reuse a pre-built native
helper, or `--debug` to skip `cargo --release`.

Au premier lancement, un assistant de configuration s'ouvre : langue, dossier de récupération, moteur de scan, et avertissement de sécurité obligatoire.

## Points à savoir avant de lancer

- Ne jamais récupérer vers le disque source.
- SSD + TRIM actif = les données effacées peuvent être irrécupérables.
- Pour les supports endommagés : créez d'abord une image disque, scannez l'image.
- Extraction limitée à 500 Mo par fichier (signalé dans l'interface et le rapport DFXML).
- Lecture brute des disques requiert privilèges admin (Windows : UAC ; macOS : élévation osascript ; Linux : `sudo`).

## Plateformes supportées

| Plateforme | Statut | Installation |
|------------|--------|--------------|
| Windows 10/11 (x64) | Production | `python scripts/build.py` → `dist\Lumina.exe` |
| macOS 10.13+ | Beta | `python scripts/build.py` → `dist/Lumina.app` |
| Linux (Ubuntu/Debian/Fedora) | Beta | `python scripts/build.py && sudo bash scripts/install_linux.sh` |

## Ce qui arrive ensuite

- Parseur APFS complet (Filesystem B-Tree walker — v1 actuelle ne fait que la détection NXSB + APSB + chiffrement).
- Scanner Rust étendu aux lecteurs physiques (`\\.\PhysicalDrive`).
- Pipeline CI/CD avec release automatique des trois OS.
