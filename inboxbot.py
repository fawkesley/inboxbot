#!/usr/bin/env python3

# Thanks https://gist.github.com/robulouski/7441883

import datetime
import imaplib
import logging
import email
import io

from email.parser import BytesParser
import email.policy

import yaml


class MessageSet():
    def __init__(self, folder, message_numbers):
        self.folder = folder
        self.message_numbers = message_numbers

    def __len__(self):
        return len(self.message_numbers)

    def __str__(self):
        return '{} - {}'.format(self.folder, ' '.join(self.message_numbers))


class SearchResults():
    def __init__(self, message_numbers, lazy_load_messages):
        self.__message_numbers = message_numbers
        self.__lazy_load_messages = lazy_load_messages

    def message_set(self):
        return MessageSet(self.__folder, self.__message_numbers)

    @property
    def messages(self):
        return self.__lazy_load_messages()


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
        logging.debug(self.c.list())

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

    def search(self, search_conditions):
        """
        See https://tools.ietf.org/html/rfc3501#section-6.4.4
        """

        folder = search_conditions.pop('folder')
        self.c.select(folder)

        search_string = str(SearchStringBuilder(search_conditions))

        logging.debug(search_string)

        typ, msgnums = self.c.search(None, search_string)
        assert typ == 'OK', typ
        assert len(msgnums) == 1, msgnums

        message_numbers = msgnums[0].decode('ascii').split()

        message_set = MessageSet(folder, message_numbers)

        logging.debug("Got {} messages: {} ".format(
            len(message_set), message_set))
        return message_set

    def load_messages(self, message_set):
        self.c.select(message_set.folder)

        for message_number in message_set.message_numbers:

            type_, crappy_data = self.c.fetch(message_number, '(RFC822)')
            assert type_ == 'OK', type_

            parser = BytesParser(policy=email.policy.default)
            email_message = parser.parsebytes(text=crappy_data[0][1])

            yield email_message


def main():
    logging.basicConfig(level=logging.DEBUG)

    with io.open('credentials.yml', 'rb') as f:
        credentials = yaml.load(f)
        print(credentials)

    mailbox = Mailbox(
        credentials['hostname'],
        credentials['username'],
        credentials['password']
    )

    ACTIONS = {
        'delete': mailbox.delete,
        'mark_read': mailbox.mark_read,
        'unsubscribe': attempt_unsubscribe,
    }

    with io.open('rules.yml', 'rb') as f:
        rules = yaml.load(f)
        logging.debug(rules)

        for rule in rules['rules']:
            logging.debug(rule)

            search_results = mailbox.search(rule['search'])

            for message in mailbox.load_messages(search_results):
                logging.debug('{} {}'.format(
                    message['from'], message['subject']))

            try:
                action_func = ACTIONS[rule['action']]
            except KeyError:
                raise NotImplementedError(rule['action'])
            else:
                action_func(search_results)


def attempt_unsubscribe(message_set):
    logging.debug("Attempt unsubscribe: {}".format(message_set))
    raise NotImplementedError


if __name__ == '__main__':
    main()
