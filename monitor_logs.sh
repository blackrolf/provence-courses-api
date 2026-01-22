#!/bin/bash

# Script de monitoring des logs en temps réel avec formatage

echo "=========================================="
echo "📊 MONITORING LOGS - Provence Courses API"
echo "=========================================="
echo ""
echo "Appuyez sur Ctrl+C pour arrêter"
echo ""

# Couleurs pour le terminal
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Fonction pour formater les logs
format_logs() {
    while IFS= read -r line; do
        # Colorer selon le niveau de log
        if [[ $line == *"ERROR"* ]] || [[ $line == *"error"* ]]; then
            echo -e "${RED}❌ $line${NC}"
        elif [[ $line == *"WARNING"* ]] || [[ $line == *"warning"* ]]; then
            echo -e "${YELLOW}⚠️  $line${NC}"
        elif [[ $line == *"SUCCESS"* ]] || [[ $line == *"success"* ]]; then
            echo -e "${GREEN}✅ $line${NC}"
        elif [[ $line == *"INFO"* ]] || [[ $line == *"info"* ]]; then
            echo -e "${CYAN}ℹ️  $line${NC}"
        elif [[ $line == *"Phase 1"* ]] || [[ $line == *"Phase 2"* ]]; then
            echo -e "${MAGENTA}🔄 $line${NC}"
        elif [[ $line == *"Saving"* ]] || [[ $line == *"save"* ]]; then
            echo -e "${BLUE}💾 $line${NC}"
        elif [[ $line == *"optimization"* ]]; then
            echo -e "${GREEN}🎯 $line${NC}"
        else
            echo "$line"
        fi
    done
}

# Suivre les logs avec formatage
sudo journalctl -u provence-courses-api -f --no-hostname | format_logs