#!/usr/bin/env bash
# ==============================================================================
# PricePulse: AWS EC2 t2.micro Free-Tier Setup Script
# Configures Docker, Python 3.11, Uvicorn service, and Nginx reverse proxy
# ==============================================================================
set -e

echo ">> Updating system packages..."
sudo yum update -y || sudo apt-get update -y

echo ">> Installing Docker and Git..."
if command -v yum >/dev/null 2>&1; then
    sudo yum install -y docker git
    sudo systemctl enable --now docker
    sudo usermod -aG docker ec2-user
elif command -v apt-get >/dev/null 2>&1; then
    sudo apt-get install -y docker.io docker-compose git
    sudo systemctl enable --now docker
    sudo usermod -aG docker ubuntu
fi

echo ">> Cloning PricePulse repository..."
if [ ! -d "pricepulse" ]; then
    git clone https://github.com/your-username/pricepulse.git
fi
cd pricepulse

echo ">> Launching PricePulse container..."
sudo docker compose -f deploy/aws/docker-compose.prod.yml up -d --build

echo ">> PricePulse is running on http://$(curl -s http://checkip.amazonaws.com):8000"
