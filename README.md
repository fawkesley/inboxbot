# Inboxbot

Manage your inbox with YAML-defined rules, for example:

```yaml
rules:

  - search:
      folder: "INBOX"
      from: "alert@updown.io"
      older_than_days: 3
      subject: "[updown alert]"
    action: "delete"
```

## Install

You'll need to run in a virtualenv:

```
virtualenv -p $(which python3) venv
. venv/bin/activate

pip install -r requirements.txt
```

## Configure

Copy and edit `rules.yml.example` and `credentials.yml.example`

```
cp credentials.yml.example credentials.yml
cp rules.yml.example rules.yml
```


## Run

```
./run.py
```
