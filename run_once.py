import asyncio
import json
import logging
from telethon import TelegramClient
from telethon.sessions import StringSession

from main import API_ID, API_HASH

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    with open('bot_data.json', 'r', encoding='utf-8') as f:
        data = json.load(f)

    accounts = data.get('accounts', {})
    channels = data.get('channels', [])
    if not accounts:
        logger.error('No accounts in bot_data.json')
        return
    if not channels:
        logger.error('No channels in bot_data.json')
        return

    # pick first active account
    phone = None
    session = None
    for ph, acc in accounts.items():
        if acc.get('active') and acc.get('session'):
            phone = ph
            session = acc.get('session')
            break

    if not phone or not session:
        logger.error('No active session found')
        return

    # pick first channel username
    ch = channels[0]
    username = ch.get('username') if isinstance(ch, dict) else str(ch).lstrip('@')
    username = username.lstrip('@')

    client = TelegramClient(StringSession(session), API_ID, API_HASH)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            logger.error('Account not authorized: %s', phone)
            return

        # resolve entity
        try:
            entity = await client.get_entity(username)
        except Exception:
            entity = await client.get_entity('@' + username)

        msgs = await client.get_messages(entity, limit=1)
        reply_id = msgs[0].id if msgs else None

        comment = 'Тестовый комментарий от автотеста.'
        if reply_id:
            res = await client.send_message(entity, comment, reply_to=reply_id)
        else:
            res = await client.send_message(entity, comment)

        logger.info('Sent test comment with id: %s', getattr(res, 'id', res))
    except Exception as e:
        logger.error('Test run failed: %s', e)
    finally:
        await client.disconnect()


if __name__ == '__main__':
    asyncio.run(main())
