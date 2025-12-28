#!/bin/bash

# TaoQuant Grid Trading - Simple Deployment Script
# Usage: sudo bash deploy.sh

set -e  # Exit on error

echo "========================================"
echo "TaoQuant Grid Trading - Deployment"
echo "========================================"

# Configuration
APP_DIR="/opt/taoquant-grid"
SERVICE_NAME="taoquant-grid"
REPO_URL="https://github.com/yourusername/taoquant-grid.git"  # Update this

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root: sudo bash deploy.sh${NC}"
    exit 1
fi

# Step 1: Install dependencies
echo -e "${GREEN}[1/6] Installing system dependencies...${NC}"
apt-get update -qq
apt-get install -y python3 python3-pip python3-venv git

# Step 2: Setup directory
echo -e "${GREEN}[2/6] Setting up application directory...${NC}"
if [ ! -d "$APP_DIR" ]; then
    mkdir -p "$APP_DIR"
    echo "Created $APP_DIR"
else
    echo "Directory $APP_DIR already exists"
fi

# Step 3: Clone or update repository
echo -e "${GREEN}[3/6] Cloning/updating repository...${NC}"
cd "$APP_DIR"
if [ -d ".git" ]; then
    echo "Updating existing repository..."
    git pull origin main
else
    echo "Cloning repository..."
    git clone "$REPO_URL" .
fi

# Step 4: Setup Python virtual environment
echo -e "${GREEN}[4/6] Setting up Python environment...${NC}"
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "Created virtual environment"
else
    echo "Virtual environment already exists"
fi

source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q

# Step 5: Configure environment
echo -e "${GREEN}[5/6] Configuring environment...${NC}"
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}WARNING: .env file not found${NC}"
    echo "Please create .env file with your Bitget API credentials"
    echo "Example:"
    cat .env.example
else
    echo ".env file found"
fi

# Step 6: Setup systemd service
echo -e "${GREEN}[6/6] Setting up systemd service...${NC}"

cat > /etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=TaoQuant Grid Trading Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${APP_DIR}
Environment="PATH=${APP_DIR}/venv/bin"
ExecStart=${APP_DIR}/venv/bin/python ${APP_DIR}/run_live.py --balance 100 --leverage 10
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd
systemctl daemon-reload
systemctl enable ${SERVICE_NAME}

echo -e "${GREEN}========================================"
echo "Deployment complete!"
echo "========================================${NC}"
echo ""
echo "Next steps:"
echo "  1. Edit API credentials: nano $APP_DIR/.env"
echo "  2. Edit bot parameters: nano /etc/systemd/system/${SERVICE_NAME}.service"
echo "  3. Start service: systemctl start ${SERVICE_NAME}"
echo "  4. Check status: systemctl status ${SERVICE_NAME}"
echo "  5. View logs: journalctl -u ${SERVICE_NAME} -f"
echo ""
echo -e "${YELLOW}Note: Make sure to configure your .env file before starting!${NC}"
