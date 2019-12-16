#!/usr/bin/env python3

# Thanks https://gist.github.com/robulouski/7441883

import datetime
import io
import email
import email.policy
import imaplib
import logging
import os
import shlex
import subprocess
import sys

from email.parser import BytesParser
from pathlib import Path, PurePath

import yaml


class MessageSet():
    def __init__(self, folder, message_numbers):
        self.folder = folder
        self.message_numbers = message_numbers

    def __len__(self):
        return len(self.message_numbers)

    def __str__(self):
        return '{} - {}'.format(self.folder, ' '.join(self.message_numbers))


class SearchStringBuilder():
    def __init__(self, search_conditions):

        search_parts = []

        for key, value in search_conditions.items():
            if key == 'from':
                search_parts.append('FROM "{}"'.format(value))

            elif key == 'older_than_days':
                date_before = datetime.date.today() - datetime.timedelta(
                    days=value
                )
                search_parts.append('BEFORE "{}"'.format(
                    date_before.strftime('%d-%b-%Y'))
                )

            elif key == 'subject':
                search_parts.append('SUBJECT "{}"'.format(value))

            elif key == 'to':
                search_parts.append('TO "{}"'.format(value))

            elif key == 'is_unread':
                if value is True:
                    search_parts.append('UNSEEN')
                else:
                    search_parts.append('SEEN')

            elif key == 'has_header':
                search_parts.append('HEADER {} ""'.format(value))

            else:
                raise NotImplementedError(
                    "Don't understand search condition `{}`".format(key)
                )

        self._imap_string = '({})'.format(' '.join(search_parts))

    def __str__(self):
        return self._imap_string


class Mailbox():
    def __init__(self, host, username, password):
        self.c = imaplib.IMAP4_SSL(host)

        self.c.login(username, password)
        status, folders = self.c.list()

        if status != "OK":
            raise RuntimeError(status)

        for folder in folders:
            logging.debug(f"folder: {folder}")

    def delete(self, message_set):
        self.c.select(message_set.folder)

        for num in message_set.message_numbers:
            logging.info("DELETE {}: {}".format(message_set.folder, num))
            self.c.store(num, '+FLAGS', '\\Deleted')

        self.c.expunge()

    def mark_read(self, message_set):
        self.c.select(message_set.folder)

        for num in message_set.message_numbers:
            logging.info("SEEN {}: {}".format(message_set.folder, num))
            self.c.store(num, '+FLAGS', '\\Seen')

    def echo(self, message_set):
        count = 0
        for email_message in self.load_email_messages(message_set):
            count += 1
            print("----------")
            print(f"From: {email_message['from']}")
            print(f"To: {email_message['to']}")
            print(f"Subject: {email_message['subject']}")

            body_email_message = email_message.get_body(preferencelist=('plain',))
            if body_email_message is not None:
                body = body_email_message.get_content()
                print(f"\n{body}...")
            else:
                print("[no text body found]")

        logging.info(f"{count} emails echoed")

    def dump(self, message_set):
        count = 0
        for email_bytes in self.load_raw_emails(message_set):
            count += 1

            filename = f"email_{count}.eml"
            logging.info(f"writing {filename}")

            with io.open(filename, "wb") as f:
                f.write(email_bytes)

        logging.info(f"{count} emails dumped")

    def run_script(self, message_set, script_path):
        # TODO: move these out of Mailbox: they don't belong here

        count = 0
        for email_bytes in self.load_raw_emails(message_set):
            count += 1

            logging.info(f"sending email to {script_path}")
            p = subprocess.Popen(
                shlex.split(script_path),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            try:
                stdout, stderr = p.communicate(email_bytes, timeout=15)
            except subprocess.TimeoutExpired:
                p.kill()
                stdout, stderr = p.communicate()

            for line in stdout.decode("utf-8").splitlines():
                logging.info(f"stdout> {line}")

            for line in stderr.decode("utf-8").splitlines():
                logging.info(f"stderr> {line}")

            if p.returncode != 0:
                raise RuntimeError(f"failed with exit code {p.returncode}")

        logging.info(f"{count} emails sent to {script_path}")

    def search(self, search_conditions):
        """
        See https://tools.ietf.org/html/rfc3501#section-6.4.4
        """

        folder = search_conditions.pop('folder')
        status, other = self.c.select(folder)
        if status != "OK":
            raise RuntimeError(f"{status} {other}")

        search_string = str(SearchStringBuilder(search_conditions))

        logging.debug(f"search string: {search_string}")

        typ, msgnums = self.c.search(None, search_string)
        assert typ == 'OK', typ
        assert len(msgnums) == 1, msgnums

        message_numbers = msgnums[0].decode('ascii').split()

        message_set = MessageSet(folder, message_numbers)

        logging.debug("Got {} messages: {} ".format(
            len(message_set), message_set))
        return message_set

    def load_email_messages(self, message_set):
        """
        load_email_messages yields an EmailMessage for each email defined in message_set
        """
        parser = BytesParser(policy=email.policy.default)

        for email_bytes in self.load_raw_emails(message_set):
            yield parser.parsebytes(text=email_bytes)

    def load_raw_emails(self, message_set):
        """
        load_raw_emails yields a slice of bytes for the raw content of each email defined
        in message_set.
        """

        self.c.select(message_set.folder)

        for message_number in message_set.message_numbers:

            type_, crappy_data = self.c.fetch(message_number, '(RFC822)')
            assert type_ == 'OK', type_

            yield crappy_data[0][1]


def main():
    logging.basicConfig(level=logging.DEBUG)

    config_dir = get_config_path()

    account_dirs = list(get_account_dirs(config_dir))
    if not account_dirs:
        print("ERROR: no config found.")
        print(f"create a subdirectory in {config_dir} containing rules.yml, credentials.yml")
        sys.exit(1)

    for account_dir in account_dirs:
        logging.info(f"running rules from {account_dir}")

        with io.open(account_dir.joinpath("credentials.yml"), "rb") as f:
            credentials = yaml.load(f)

        with io.open(account_dir.joinpath("rules.yml"), "rb") as f:
            rules = yaml.load(f)
            logging.debug(f"rules: {rules}")

        mailbox = Mailbox(
            credentials['hostname'],
            credentials['username'],
            credentials['password']
        )

        run_rules(mailbox, rules)


def get_config_path():
    """
    returns a Path from the environment variable XDG_CONFIG_HOME or ~/.config if unset
    """

    try:
        return PurePath(os.environ["XDG_CONFIG_HOME"])
    except KeyError:
        return Path.home().joinpath(".config", "inboxbot", "accounts.d")


def get_account_dirs(config_dir):
    """
    get_account_dirs returns subdirectories of ${XDG_CONFIG_HOME}/inboxbot/accounts.d
    (defaulting to ~/.config/)
    """

    try:
        for fn in os.listdir(config_dir):
            if os.path.isdir(config_dir.joinpath(fn)) and ".disabled" not in fn:
                yield config_dir.joinpath(fn)

    except FileNotFoundError:
        return


def run_rules(mailbox, rules):
    ACTIONS = {
        'delete': mailbox.delete,
        'mark_read': mailbox.mark_read,
        'unsubscribe': attempt_unsubscribe,
        'echo': mailbox.echo,
        'dump': mailbox.dump,
        'run_script': mailbox.run_script,
    }

    for rule in rules['rules']:
        logging.debug(f"running rule: {rule}")

        search_results = mailbox.search(rule['search'])

        if "action" in rule:
            actions = [rule["action"]]
        elif "actions" in rule:
            actions = rule["actions"]
        else:
            raise ValueError("every rule needs `action` or `actions`")

        for action in actions:
            if isinstance(action, str):
                action_name = action
                action_kwargs = {}

            elif isinstance(action, dict):
                action_name = action.pop("name")
                action_kwargs = action

            try:
                action_func = ACTIONS[action_name]
            except KeyError:
                raise NotImplementedError(rule['action'])
            else:
                action_func(search_results, **action_kwargs)


def attempt_unsubscribe(message_set):
    logging.debug("Attempt unsubscribe: {}".format(message_set))
    raise NotImplementedError


if __name__ == '__main__':
    main()
