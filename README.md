# Lumina

[![Build & Test](https://github.com/Louis765900/Lumina/actions/workflows/build.yml/badge.svg?branch=main)](https://github.com/Louis765900/Lumina/actions/workflows/build.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey.svg)](#plateformes-supportées)

**Récupération de données — interface rétro Windows 98, moteur moderne, V2 Windows.**

Version actuelle : **v2.0.0-rc1**.

Lumina retrouve vos fichiers perdus sur disques durs, SSD, clés USB et cartes SD. Pas de résultats inventés : chaque fichier affiché provient d'une vraie analyse de votre disque.

---

## Ce que Lumina fait

- **Quick Scan** — lit les métadonnées NTFS/MFT quand elles sont disponibles pour retrouver les fichiers supprimés récemment.
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

La V2.0 est publiee Windows-first. Les builds Linux et macOS restent planifies,
mais ne sont pas annonces comme supportes pour cette release candidate.

Pass `--skip-rust` to reuse a pre-built native helper, or `--debug` to skip
`cargo --release`.

Au premier lancement, un assistant de configuration s'ouvre : langue, dossier de récupération, moteur de scan, et avertissement de sécurité obligatoire.

## Points à savoir avant de lancer

- Ne jamais récupérer vers le disque source.
- SSD + TRIM actif = les données effacées peuvent être irrécupérables.
- Pour les supports endommagés : créez d'abord une image disque, scannez l'image.
- L'extraction lit les fichiers recuperes en streaming. Si la source se termine trop tot,
  Lumina marque clairement le fichier comme partiel.
- Lecture brute des disques requiert les droits Administrateur sur Windows (invite UAC).

## Plateformes supportées

| Plateforme | Statut | Installation |
|------------|--------|--------------|
| Windows 10/11 (x64) | Release candidate V2 | `python scripts/build.py` -> `dist\Lumina.exe` |
| Linux | Planifie V2.1 | Non inclus dans cette RC |
| macOS | Planifie V2.2 | Non inclus dans cette RC |

## Ce qui arrive ensuite

- Parseur APFS complet (Filesystem B-Tree walker ; la version actuelle ne fait que la detection NXSB + APSB + chiffrement).
- Scanner Rust étendu aux lecteurs physiques (`\\.\PhysicalDrive`).
- Stabilisation de la release Windows, puis travaux Linux V2.1 et macOS V2.2.
