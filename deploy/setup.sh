#!/bin/bash
# ================================================================
# Deploy Script: NLP Summarization Pipeline
# Nginx + Gunicorn + Systemd
# ================================================================
set -e

PROJECT_DIR="/home/ubuntu/academic-text-summarization-id"
SERVICE_NAME="nlp-summarization"

echo "=============================="
echo " NLP Summarization - Deploy"
echo "=============================="

# 1. Install Nginx
echo "[1/6] Installing Nginx..."
sudo apt-get update -qq
sudo apt-get install -y -qq nginx

# 2. Install Python dependencies
echo "[2/6] Installing Python dependencies..."
python3 -m pip install --no-cache-dir -r "$PROJECT_DIR/requirements.txt"

# 3. Download NLTK data
echo "[3/6] Downloading NLTK data..."
python3 -c "import nltk; nltk.download('punkt', quiet=True); nltk.download('punkt_tab', quiet=True); nltk.download('stopwords', quiet=True)"

# 4. Create log directory
echo "[4/6] Creating log directory..."
sudo mkdir -p /var/log/nlp-summarization
sudo chown ubuntu:ubuntu /var/log/nlp-summarization

# 5. Setup systemd service
echo "[5/6] Setting up systemd service..."
sudo cp "$PROJECT_DIR/deploy/nlp-summarization.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable $SERVICE_NAME
sudo systemctl restart $SERVICE_NAME

# Tunggu app siap (PySastrawi loading ~15 detik)
echo "    Menunggu app siap (±15 detik)..."
sleep 15

# Cek status
if sudo systemctl is-active --quiet $SERVICE_NAME; then
    echo "    ✓ Service $SERVICE_NAME berjalan"
else
    echo "    ✗ Service gagal. Cek log: sudo journalctl -u $SERVICE_NAME -n 50"
    exit 1
fi

# 6. Setup Nginx
echo "[6/6] Configuring Nginx..."
sudo cp "$PROJECT_DIR/deploy/nginx-nlp-summarization.conf" /etc/nginx/sites-available/$SERVICE_NAME
sudo ln -sf /etc/nginx/sites-available/$SERVICE_NAME /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# Test & restart nginx
sudo nginx -t
sudo systemctl restart nginx

echo ""
echo "=============================="
echo " ✓ Deploy selesai!"
echo "=============================="
echo ""
echo " App berjalan di: http://$(hostname -I | awk '{print $1}')"
echo ""
echo " Perintah berguna:"
echo "   sudo systemctl status $SERVICE_NAME   # Cek status app"
echo "   sudo systemctl restart $SERVICE_NAME  # Restart app"
echo "   sudo journalctl -u $SERVICE_NAME -f   # Lihat log realtime"
echo "   sudo systemctl status nginx           # Cek status nginx"
echo ""
