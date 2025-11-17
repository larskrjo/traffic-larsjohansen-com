pushd /home/ec2-user/traffic-larsjohansen-com/backend
docker build -t api-traffic:latest .
docker compose -p api-traffic down
docker compose -p api-traffic up -d
docker image prune -a -f
popd
