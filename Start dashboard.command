#!/bin/zsh
cd -- "${0:A:h}"
if curl --silent --fail http://127.0.0.1:4318/api/sessions >/dev/null; then
  open http://127.0.0.1:4318
  exit
fi
exec python3 server.py --open
