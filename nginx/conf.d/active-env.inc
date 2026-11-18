# GACHIMURA Active Upstream Environment
# deploy.sh 에 의해 Blue 또는 Green으로 자동 전환됩니다.

set $backend_upstream http://gachimura-backend-blue:3000;
set $frontend_upstream http://gachimura-frontend-blue:3000;
