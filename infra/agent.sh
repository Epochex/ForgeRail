#!/bin/sh
set -eu
while [ ! -s /shared/agent-secret ]; do sleep 1; done
exec java -jar /opt/agent.jar -url http://jenkins:8080/ -name linux-lab -webSocket -workDir /home/agent -secret @/shared/agent-secret
