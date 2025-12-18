import asyncio
import json
import logging
from telethon import TelegramClient
from telethon.sessions import StringSession

from main import API_ID, API_HASH

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def try_send(session, phone, username, comment):
    client = TelegramClient(StringSession(session), API_ID, API_HASH)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            return False, f'Account not authorized: {phone}'
        try:
            entity = await client.get_entity(username)
        except Exception:
            entity = await client.get_entity('@' + username)
        msgs = await client.get_messages(entity, limit=1)
        reply_id = msgs[0].id if msgs else None
        if reply_id:
            await client.send_message(entity, comment, reply_to=reply_id)
        else:
            await client.send_message(entity, comment)
        return True, 'Sent'
    except Exception as e:
        return False, str(e)
    finally:
        await client.disconnect()


async def main():
    with open('bot_data.json', 'r', encoding='utf-8') as f:
        data = json.load(f)

    accounts = data.get('accounts', {})
    channels = data.get('channels', [])
    if not accounts or not channels:
        logger.error('Missing accounts or channels in bot_data.json')
        return

    comment = 'Тестовый автокомментарий: попытка отправки.'

    for ph, acc in accounts.items():
        session = acc.get('session')
        active = acc.get('active')
        if not active or not session:
            logger.info('Skipping inactive or missing session for %s', ph)
            continue
        logger.info('Trying account %s', ph)
        for ch in channels:
            username = ch.get('username') if isinstance(ch, dict) else str(ch).lstrip('@')
            username = username.lstrip('@')
            logger.info(' -> Trying channel %s', username)
            ok, msg = await try_send(session, ph, username, comment)
            logger.info('    Result: %s, %s', ok, msg)
            if ok:
                logger.info('Success: account %s -> channel %s', ph, username)
                return

    logger.info('Finished all accounts/channels without success')


if __name__ == '__main__':
    asyncio.run(main())
