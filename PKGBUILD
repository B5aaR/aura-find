pkgname=aura-find
pkgver=1.1.0
pkgrel=2
pkgdesc="A modern, GUI-based Arch Linux application discovery tool"
arch=('any')
depends=('python' 'python-pyqt6' 'python-requests')
source=('gui.py'
        'aura-find.desktop'
        'real_db.json')
sha256sums=('SKIP'
            'SKIP'
            'SKIP')

package() {
    # 1. Create system directories
    install -dm755 "$pkgdir/usr/share/$pkgname/data"
    install -dm755 "$pkgdir/usr/bin"
    install -dm755 "$pkgdir/usr/share/applications"

    # 2. Install the Python GUI script
    install -m755 gui.py "$pkgdir/usr/share/$pkgname/gui.py"

    # 3. Install the offline database into the system's data folder
    install -m644 real_db.json "$pkgdir/usr/share/$pkgname/data/real_db.json"

    # 4. Install the desktop entry for the app menu
    install -m644 aura-find.desktop "$pkgdir/usr/share/applications/"

    # 5. Create the global command
    echo '#!/bin/bash' > "$pkgdir/usr/bin/$pkgname"
    echo 'python /usr/share/aura-find/gui.py "$@"' >> "$pkgdir/usr/bin/$pkgname"
    chmod +x "$pkgdir/usr/bin/$pkgname"
}
