import asyncio, json, re
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon import functions
from main import API_ID, API_HASH

async def run():
    with open('bot_data.json','r',encoding='utf-8') as f:
        data=json.load(f)
    acc = data.get('accounts',{}).get('79939230850')
    if not acc:
        print('no acc')
        return
    session = acc.get('session')
    username = 'NFT_Giveaway_TG'
    client = TelegramClient(StringSession(session), API_ID, API_HASH)
    await client.connect()
    try:
        entity = await client.get_entity(username)
        full = await client(functions.channels.GetFullChannelRequest(channel=entity))
        print('full keys:', dir(full)[:10])
        linked = None
        if getattr(full,'full_chat',None) and getattr(full.full_chat,'linked_chat_id',None):
            linked = full.full_chat.linked_chat_id
        elif getattr(full,'chats',None):
            for ch in full.chats:
                if getattr(ch,'linked_chat_id',None):
                    linked = ch.linked_chat_id
                    break
        print('linked:', linked)
        if not linked:
            print('no linked')
            return
        discussion = await client.get_entity(linked)
        msgs = await client.get_messages(discussion, limit=1)
        print('last discussion msg id:', msgs[0].id if msgs else None)
        try:
            res = await client.send_message(discussion, 'Test comment to discussion', reply_to=msgs[0].id if msgs else None)
            print('sent', getattr(res,'id',res))
        except Exception as e:
            print('send error', e)
    finally:
        await client.disconnect()

asyncio.run(run())
