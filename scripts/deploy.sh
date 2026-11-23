#!/bin/bash
set -euo pipefail

# ==============================================================================
# 기존 환경을 유지한 채 새 환경을 검사하고 Nginx 연결을 전환합니다.
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"
CONF_DIR="${PROJECT_DIR}/nginx/conf.d"
ACTIVE_ENV_FILE="${CONF_DIR}/active-env.inc"

cd "${PROJECT_DIR}"

# 빌드 전 안전 여유이며 모든 빌드의 성공을 보장하는 크기는 아닙니다.
MIN_FREE_KIB=$((4 * 1024 * 1024))
AVAILABLE_KIB=$(df -Pk "${PROJECT_DIR}" | awk 'NR == 2 { print $4 }')
if ! [[ "$AVAILABLE_KIB" =~ ^[0-9]+$ ]] || (( AVAILABLE_KIB < MIN_FREE_KIB )); then
    echo "[ERROR] 배포 전 최소 4GiB의 여유 공간을 확보해주세요. 실행 중인 서비스는 변경하지 않았습니다."
    exit 1
fi

mkdir -p "${CONF_DIR}"

echo "=============================================================================="
echo "🚀 [GACHIMURA] 무중단 배포 프로세스 시작"
echo "=============================================================================="

# 이전 단일 환경은 DB·포트 이전을 확인한 뒤 별도로 전환해야 합니다.
for service in nginx database; do
    if docker inspect "project-gachimura-main-deployment-${service}-1" >/dev/null 2>&1; then
        echo "[ERROR] 기존 단일 환경이 남아 있습니다. DB 저장소·포트 전환 확인 전 배포를 중단합니다."
        exit 1
    fi
done

# 2. 현재 실행 중인 활성 환경(Active) 파악
IS_BLUE_RUNNING=$(docker ps --filter "name=gachimura-backend-blue" --filter "status=running" -q)
IS_GREEN_RUNNING=$(docker ps --filter "name=gachimura-backend-green" --filter "status=running" -q)

if [ -n "$IS_BLUE_RUNNING" ] && [ -n "$IS_GREEN_RUNNING" ]; then
    echo "[ERROR] 두 환경이 모두 실행 중입니다. 현재 연결 대상을 확인한 뒤 재시도하세요."
    exit 1
elif [ -n "$IS_BLUE_RUNNING" ]; then
    CURRENT="blue"
    TARGET="green"
    TARGET_BACKEND_PORT=3002
    TARGET_FRONTEND_PORT=4002
    TARGET_BACKEND_HOST="gachimura-backend-green"
    TARGET_FRONTEND_HOST="gachimura-frontend-green"
elif [ -n "$IS_GREEN_RUNNING" ]; then
    CURRENT="green"
    TARGET="blue"
    TARGET_BACKEND_PORT=3001
    TARGET_FRONTEND_PORT=4001
    TARGET_BACKEND_HOST="gachimura-backend-blue"
    TARGET_FRONTEND_HOST="gachimura-frontend-blue"
else
    # 최초 배포 시 (둘 다 미기동 상태)
    CURRENT="none"
    TARGET="blue"
    TARGET_BACKEND_PORT=3001
    TARGET_FRONTEND_PORT=4001
    TARGET_BACKEND_HOST="gachimura-backend-blue"
    TARGET_FRONTEND_HOST="gachimura-frontend-blue"
fi

# 자동 배포는 사용 중인 DB 저장소를 다른 볼륨으로 바꾸지 않습니다.
PLANNED_DB_VOLUME=$(docker compose -p gachimura-base -f docker-compose.base.yml config --format json | python3 -c '
import json, sys
try:
    volume = json.load(sys.stdin)["volumes"]["mysql_data"]
    if volume.get("external") is not True or not isinstance(volume.get("name"), str) or not volume["name"]:
        raise ValueError()
    print(volume["name"])
except (KeyError, TypeError, ValueError):
    raise SystemExit("기존 외부 DB 볼륨 설정을 확인해주세요.")
')
docker volume inspect "$PLANNED_DB_VOLUME" >/dev/null
DATABASE_CONTAINER_ID=$(docker ps -aq --filter "name=^/gachimura-db$")
if [ -n "$DATABASE_CONTAINER_ID" ]; then
    CURRENT_DB_VOLUME=$(docker inspect "$DATABASE_CONTAINER_ID" --format '{{range .Mounts}}{{if eq .Destination "/var/lib/mysql"}}{{.Name}}{{end}}{{end}}')
    if [ "$CURRENT_DB_VOLUME" != "$PLANNED_DB_VOLUME" ]; then
        echo "[ERROR] 현재 DB와 배포 설정의 저장소가 다릅니다. 확인된 복구 절차로 먼저 연결한 뒤 재시도하세요."
        exit 1
    fi
fi

# git reset이 되돌린 연결 설정을 현재 가동 환경으로 복원한 뒤 프록시를 갱신합니다.
ACTIVE="${CURRENT}"
if [ "$ACTIVE" = "none" ]; then ACTIVE="$TARGET"; fi
cat > "$ACTIVE_ENV_FILE" << EOF
set \$backend_upstream http://gachimura-backend-${ACTIVE}:3000;
set \$frontend_upstream http://gachimura-frontend-${ACTIVE}:3000;
EOF
echo ">>> [1/7] 기존 DB 저장소 확인 및 Base 설정 갱신..."
docker compose -p gachimura-base -f docker-compose.base.yml build nginx
docker compose -p gachimura-base -f docker-compose.base.yml run --rm --no-deps nginx nginx -t
docker compose -p gachimura-base -f docker-compose.base.yml up -d

echo ">>> [2/7] 현재 활성 환경: [${CURRENT}] ➡️ 신규 배포 대상: [${TARGET}]"

# 3. 신규 Target 환경 빌드 및 기동
echo ">>> [3/7] [${TARGET}] 컨테이너 빌드 및 기동 시작..."
docker compose -p "gachimura-${TARGET}" -f "docker-compose.${TARGET}.yml" up -d --build

# 4. Health Check (최대 60초 대기)
echo ">>> [4/7] [${TARGET}] 서비스 Health Check 시작 (최대 60초)..."
MAX_RETRIES=30
RETRY_INTERVAL=2

# 4-1. 백엔드 헬스체크 (/api/health)
BACKEND_HEALTHY=false
for i in $(seq 1 $MAX_RETRIES); do
    # NestJS 전역 접두사 /api 적용: /api/health 우선 확인 후 /health 폴백
    STATUS=$(curl --connect-timeout 2 --max-time 5 -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${TARGET_BACKEND_PORT}/api/health" || true)
    if [ "$STATUS" != "200" ]; then
        STATUS=$(curl --connect-timeout 2 --max-time 5 -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${TARGET_BACKEND_PORT}/health" || true)
    fi

    if [ "$STATUS" = "200" ]; then
        echo "  ✅ Backend Health Check 성공! (HTTP 200, 시도: ${i}/${MAX_RETRIES})"
        BACKEND_HEALTHY=true
        break
    fi
    echo "  ⏳ Backend 응답 대기 중 (HTTP ${STATUS:-N/A}, 시도: ${i}/${MAX_RETRIES})..."
    sleep $RETRY_INTERVAL
done

# 4-2. 프론트엔드 헬스체크 (/)
FRONTEND_HEALTHY=false
if [ "$BACKEND_HEALTHY" = "true" ]; then
    for i in $(seq 1 $MAX_RETRIES); do
        STATUS=$(curl --connect-timeout 2 --max-time 5 -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${TARGET_FRONTEND_PORT}/" || true)
        if [ "$STATUS" = "200" ] || [ "$STATUS" = "301" ] || [ "$STATUS" = "302" ] || [ "$STATUS" = "307" ] || [ "$STATUS" = "308" ]; then
            echo "  ✅ Frontend Health Check 성공! (HTTP ${STATUS}, 시도: ${i}/${MAX_RETRIES})"
            FRONTEND_HEALTHY=true
            break
        fi
        echo "  ⏳ Frontend 응답 대기 중 (HTTP ${STATUS:-N/A}, 시도: ${i}/${MAX_RETRIES})..."
        sleep $RETRY_INTERVAL
    done
fi

# 5. 헬스체크 실패 시 즉시 자동 롤백
if [ "$BACKEND_HEALTHY" != "true" ] || [ "$FRONTEND_HEALTHY" != "true" ]; then
    echo "🚨 [ERROR] [${TARGET}] 서비스 Health Check 실패! 즉시 자동 롤백을 수행합니다."
    echo "--- Backend Logs ---"
    docker logs --tail 30 "gachimura-backend-${TARGET}" || true
    echo "--- Frontend Logs ---"
    docker logs --tail 30 "gachimura-frontend-${TARGET}" || true

    echo ">>> 신규 [${TARGET}] 컨테이너 폐기 중..."
    docker compose -p "gachimura-${TARGET}" -f "docker-compose.${TARGET}.yml" down
    if [ "$CURRENT" != "none" ]; then
        echo ">>> 기존 [${CURRENT}] 환경이 계속 서비스 중이므로 장애 없이 유지됩니다."
    fi
    exit 1
fi

# 6. Nginx 설정 검사 후 새 환경으로 연결 전환
echo ">>> [5/7] Nginx Upstream을 [${TARGET}]으로 전환 중..."
cat << EOF > "${ACTIVE_ENV_FILE}"
# Auto-generated by deploy.sh at $(date)
set \$backend_upstream http://${TARGET_BACKEND_HOST}:3000;
set \$frontend_upstream http://${TARGET_FRONTEND_HOST}:3000;
EOF

if ! docker exec gachimura-nginx nginx -t || ! docker exec gachimura-nginx nginx -s reload; then
    cat > "$ACTIVE_ENV_FILE" << EOF
set \$backend_upstream http://gachimura-backend-${ACTIVE}:3000;
set \$frontend_upstream http://gachimura-frontend-${ACTIVE}:3000;
EOF
    echo "[ERROR] Nginx 전환에 실패했습니다. 기존 환경과 신규 컨테이너를 유지합니다."
    exit 1
fi
echo "  ✅ Nginx 리로드 완료! 트래픽을 [${TARGET}]으로 전환했습니다."

# 7. 이전(Current) 환경 정리 및 이미지 Prune
if [ "$CURRENT" != "none" ]; then
    echo ">>> [6/7] 이전 환경 [${CURRENT}] 정상 종료 대기 (진행 중인 커넥션 보호 5초)..."
    sleep 5
    docker compose -p "gachimura-${CURRENT}" -f "docker-compose.${CURRENT}.yml" down
    echo "  ✅ 이전 환경 [${CURRENT}] 컨테이너 안전 종료 완료."
fi

echo ">>> [7/7] 미사용 도커 이미지 정리 (Docker image prune)..."
docker image prune -f

echo "=============================================================================="
echo "🎉 [GACHIMURA] 무중단 배포 완료! [${TARGET}] 환경 가동 중"
echo "=============================================================================="
