# 🔍 Aura-Find

A modern, fast, GUI-based application discovery tool tailored for Arch Linux. 

Aura-Find allows you to instantly search for Linux application alternatives, pulling live data from the official Arch repositories, the AUR, and a local offline database. Built with Python and PyQt6, it integrates beautifully into modern Linux desktop environments like KDE Plasma.

## ✨ Features
* **Lightning Fast:** Queries the Arch API and AUR simultaneously.
* **Offline Database:** Falls back to a local index parsed directly from the Arch Wiki.
* **Native Look & Feel:** Uses PyQt6 for a smooth, dark-mode, system-integrated UI.
* **Smart Logos:** Automatically fetches application icons on the fly using DuckDuckGo favicons.
* **Click-to-Copy:** Instantly copies the `pacman` or `yay` installation command to your clipboard.

## 📦 Installation

Since Aura-Find is packaged with a standard `PKGBUILD`, installing it on any Arch-based system (like CachyOS) is incredibly simple.

1. Clone this repository:
   ```bash
   git clone https://github.com/B5aaR/aura-find.git https://github.com/B5aaR/aura-find.git
   cd aura-find
Build and install the package:

Bash
makepkg -si
🚀 Usage
Once installed, Aura-Find functions as a native system application.

Press your Super (Windows) key, type Aura-Find, and launch it directly from your app menu.

Alternatively, launch it from the terminal by typing aura-find.

🛠️ Built With
Python 3

PyQt6

Arch Linux APIs
