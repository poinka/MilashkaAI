#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Functions
check_dependencies() {
    echo -e "${YELLOW}Checking dependencies...${NC}"
    command -v docker >/dev/null 2>&1 || { echo -e "${RED}Docker is required but not installed.${NC}" >&2; exit 1; }
    command -v docker-compose >/dev/null 2>&1 || { echo -e "${RED}Docker Compose is required but not installed.${NC}" >&2; exit 1; }
}

start_services() {
    echo -e "${YELLOW}Starting MilashkaAI services...${NC}"
    docker-compose up -d
    echo -e "${GREEN}Services started successfully.${NC}"
}

stop_services() {
    echo -e "${YELLOW}Stopping MilashkaAI services...${NC}"
    docker-compose down
    echo -e "${GREEN}Services stopped successfully.${NC}"
}

backup_data() {
    echo -e "${YELLOW}Creating backup...${NC}"
    BACKUP_DIR="backups"
    BACKUP_FILE="${BACKUP_DIR}/backup_$(date +%Y%m%d_%H%M%S).tar.gz"
    
    mkdir -p "${BACKUP_DIR}"
    
    # Stop services before backup
    docker-compose down
    
    # Create backup
    tar -czf "${BACKUP_FILE}" uploads/ falkordb_data/
    
    # Restart services
    docker-compose up -d
    
    echo -e "${GREEN}Backup created successfully: ${BACKUP_FILE}${NC}"
}

restore_backup() {
    if [ -z "$1" ]; then
        echo -e "${RED}Please specify backup file to restore.${NC}"
        exit 1
    }
    
    echo -e "${YELLOW}Restoring from backup: $1${NC}"
    
    # Stop services before restore
    docker-compose down
    
    # Restore from backup
    tar -xzf "$1"
    
    # Restart services
    docker-compose up -d
    
    echo -e "${GREEN}Restore completed successfully.${NC}"
}

check_health() {
    echo -e "${YELLOW}Checking service health...${NC}"
    
    # Check server health
    SERVER_HEALTH=$(curl -s http://localhost:8000/health)
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}Server is healthy${NC}"
    else
        echo -e "${RED}Server health check failed${NC}"
    fi
    
    # Check FalkorDB health
    FALKORDB_HEALTH=$(docker-compose exec falkordb redis-cli ping)
    if [ "$FALKORDB_HEALTH" == "PONG" ]; then
        echo -e "${GREEN}FalkorDB is healthy${NC}"
    else
        echo -e "${RED}FalkorDB health check failed${NC}"
    fi
}

show_logs() {
    service="$1"
    if [ -z "$service" ]; then
        docker-compose logs --tail=100 -f
    else
        docker-compose logs --tail=100 -f "$service"
    fi
}

update_services() {
    echo -e "${YELLOW}Updating services...${NC}"
    git pull
    docker-compose pull
    docker-compose build
    docker-compose up -d
    echo -e "${GREEN}Services updated successfully.${NC}"
}

# Main script
case "$1" in
    start)
        check_dependencies
        start_services
        ;;
    stop)
        stop_services
        ;;
    restart)
        stop_services
        start_services
        ;;
    backup)
        backup_data
        ;;
    restore)
        restore_backup "$2"
        ;;
    health)
        check_health
        ;;
    logs)
        show_logs "$2"
        ;;
    update)
        update_services
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|backup|restore|health|logs|update}"
        exit 1
        ;;
esac

exit 0
