#!/bin/zsh

NAME=$1

if [ -z "$NAME" ]; then
  echo "Usage: create_job.sh job-name"
  exit 1
fi

cd ~/Projects/research-hub/jobs
cp -r ../research-assistant/templates/job-template "$NAME"
cd "$NAME"
git init

echo "Created job: $NAME"