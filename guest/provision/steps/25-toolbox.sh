# Software the bots work with: what their computer-control and browser tools
# drive, plus everyday tools for documents, media, data, and code.

apt_install \
    scrot xclip tesseract-ocr tesseract-ocr-eng \
    chromium fonts-liberation2 \
    imagemagick poppler-utils pandoc ffmpeg \
    ripgrep fd-find sqlite3 zip unzip p7zip-full file tree htop \
    nodejs npm

# Debian names fd's binary fdfind; most people and models expect fd.
ln -sf /usr/bin/fdfind /usr/local/bin/fd
