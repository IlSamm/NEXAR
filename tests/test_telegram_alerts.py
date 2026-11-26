"""Avvisi Telegram quando Telegram o la rete sono giù: restano in ordine, nessuno si perde, i ritardati portano l'ora."""
from urllib.error import HTTPError

from telegram_bot import TelegramBot


class Fake:
    config = {'telegram': {'token': 'x', 'allowed_user_id': 5}}


def bot_with(results):
    bot = TelegramBot(Fake()); bot.user_id = 5; sent = []
    def send(chat, text, markup=None):
        r = results.pop(0) if results else 'ok'
        if isinstance(r, Exception): raise r
        sent.append(text)
    bot.send = send
    return bot, sent


def test_alerts_wait_in_order_and_carry_the_time_when_late():
    down = HTTPError('u', 502, 'Bad Gateway', {}, None)
    bot, sent = bot_with([down, down])
    bot.notify('primo'); bot.notify('secondo')
    bot.flush_notifications(); bot.flush_notifications()
    assert sent == [] and len(bot.notifications) == 2 and bot.notify_down    # Telegram giù: restano lì, in ordine
    at = bot.notifications[0][0]
    bot.flush_notifications(now=at + 600)                                     # torna su 10 minuti dopo
    assert len(sent) == 2 and sent[0].endswith('primo') and sent[1].endswith('secondo') and '🕒' in sent[0]
    assert not bot.notifications and not bot.notify_down


def test_alert_telegram_will_never_accept_is_dropped():
    bot, sent = bot_with([HTTPError('u', 400, 'Bad Request', {}, None)])
    bot.notify('rotto'); bot.notify('buono')
    bot.flush_notifications()
    assert sent == ['buono'] and not bot.notifications


def test_fresh_alert_has_no_time_prefix():
    bot, sent = bot_with([])
    bot.notify('subito'); bot.flush_notifications()
    assert sent == ['subito']
