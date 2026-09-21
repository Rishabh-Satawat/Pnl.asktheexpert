# Private Quant Desk P&L Engine - VPS Deployment Guide
# Recommended path: VPS + Docker + Nginx + Let's Encrypt SSL
# Replace YOUR_SUBDOMAIN / YOUR_DOMAIN / YOUR_SERVER_IP throughout.

## 1. Create a VPS (if you don't have one)
#   - DigitalOcean / AWS Lightsail / Azure: Ubuntu 22.04 LTS, 2GB RAM, 1 vCPU (~$6-12/mo)
#   - Note the server's public IP.

## 2. Point your subdomain DNS to the server
#   In your domain registrar's DNS panel, add:
#     Type: A      Name: <subdomain>   Value: <YOUR_SERVER_IP>   TTL: 300
#   (e.g. Name: "desk"  ->  desk.yourdomain.com)
#   Wait 5-10 min for DNS to propagate.

## 3. SSH into the server
#   ssh root@YOUR_SERVER_IP

## 4. Install Docker + Compose
#   curl -fsSL https://get.docker.com | sh
#   sudo systemctl enable --now docker

## 5. Upload the project
#   From your local machine (in project folder):
#   scp -r . root@YOUR_SERVER_IP:/opt/quant-desk
#   ssh root@YOUR_SERVER_IP "cd /opt/quant-desk && cp .env.example .env && nano .env"
#   -> Paste your real GEMINI_API_KEY and APP_ACCESS_PASSWORD into .env

## 6. Build & run
#   ssh root@YOUR_SERVER_IP
#   cd /opt/quant-desk
#   docker compose up -d --build
#   docker compose ps          # confirm "healthy"

## 7. Install Nginx + Let's Encrypt SSL
#   sudo apt update && sudo apt install -y nginx certbot python3-certbot-nginx
#   sudo cp deploy/nginx-quant-desk.conf /etc/nginx/sites-available/quant-desk
#   sudo nano /etc/nginx/sites-available/quant-desk   # replace YOUR_SUBDOMAIN/YOUR_DOMAIN
#   sudo ln -s /etc/nginx/sites-available/quant-desk /etc/nginx/sites-enabled/
#   sudo nginx -t
#   sudo systemctl reload nginx
#   sudo certbot --nginx -d YOUR_SUBDOMAIN.YOUR_DOMAIN   # auto HTTPS

## 8. Done!
#   Open https://YOUR_SUBDOMAIN.YOUR_DOMAIN in your browser.
#   You'll be prompted for the APP_ACCESS_PASSWORD you set.

## 9. Backups (do this weekly)
#   docker exec quant-desk sh -c "sqlite3 /app/data/quant_desk.db '.backup /app/data/backup.db'"
#   docker cp quant-desk:/app/data/backup.db ./backup-$(date +%F).db
#   (Or add a cron job to copy /opt/quant-desk/data/quant_desk.db to cloud storage.)

## 10. Updates
#   cd /opt/quant-desk && git pull && docker compose up -d --build