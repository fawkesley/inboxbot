.PHONY: run
run:
	pipenv sync
	pipenv run ./inboxbot.py
