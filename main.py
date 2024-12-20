import os
import asyncio
import aiofiles
import aiosqlite
import logging
from aiohttp import web, ClientSession
from dotenv import load_dotenv
from create_db import create_database
import sys
import subprocess

# Загрузка переменных окружения из .env файла
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("app.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Получение ключей и идентификаторов из переменных окружения
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WAZZUP24_API_KEY = os.getenv("WAZZUP24_API_KEY")
WAZZUP24_CHANNEL_ID = os.getenv("WAZZUP24_CHANNEL_ID")
DATABASE = 'database.db'

async def create_thread(app):
    url = "https://api.openai.com/v1/threads"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}",
    }
    payload = {}

    async with app["client_session"].post(url, headers=headers, json=payload) as resp:
        if resp.status == 200:
            data = await resp.json()
            thread_id = data.get("id")
            logger.info(f"Создан новый тред: {thread_id}")
            return thread_id
        else:
            text = await resp.text()
            logger.error(f"Ошибка при создании треда: {resp.status} - {text}")
            return None

async def add_message_to_thread(app, thread_id, role, content):
    url = f"https://api.openai.com/v1/threads/{thread_id}/messages"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}"
    }
    payload = {
        "role": role,
        "content": content
    }

    async with app["client_session"].post(url, headers=headers, json=payload) as resp:
        if resp.status in [200, 201]:
            data = await resp.json()
            logger.info(f"Сообщение добавлено в тред {thread_id}: {content}")
            return data
        else:
            text = await resp.text()
            logger.error(f"Ошибка при добавлении сообщения в тред {thread_id}: {resp.status} - {text}")
            return None

async def create_and_poll_run(app, thread_id):
    # Перечитываем .env на случай, если ассистент был создан сейчас
    load_dotenv()
    assistant_id = os.getenv("ASSISTANT_ID")
    if not assistant_id:
        logger.error("ASSISTANT_ID не найден после запуска create_assistant.py")
        return None

    url = "https://api.openai.com/v1/threads/runs/create_and_poll"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}",
    }
    payload = {
        "thread_id": thread_id,
        "assistant_id": assistant_id
    }

    async with app["client_session"].post(url, headers=headers, json=payload) as resp:
        if resp.status in [200, 201]:
            data = await resp.json()
            logger.info(f"Run создан и опрошен для треда {thread_id}. Статус: {data.get('status')}")
            return data
        else:
            text = await resp.text()
            logger.error(f"Ошибка при запуске ассистента для треда {thread_id}: {resp.status} - {text}")
            return None

def extract_assistant_message(messages):
    for message in messages:
        if message.get("role") == "assistant":
            content = message.get("content", [])
            text_parts = [
                block["text"]["value"]
                for block in content
                if block.get("type") == "text" and "value" in block.get("text", {})
            ]
            return "\n".join(text_parts)
    return None

async def send_wazzup24_message(app, chat_id, message_text):
    url = "https://api.wazzup24.com/v3/message"
    headers = {
        "Authorization": f"Bearer {WAZZUP24_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "channelId": WAZZUP24_CHANNEL_ID,
        "chatId": chat_id,
        "chatType": "whatsapp",
        "text": message_text
    }

    async with app["client_session"].post(url, headers=headers, json=payload) as resp:
        if resp.status not in [200, 201]:
            text = await resp.text()
            logger.error(f"Ошибка при отправке сообщения пользователю {chat_id}: {resp.status} - {text}")
        else:
            logger.info(f"Сообщение успешно отправлено пользователю {chat_id}")

async def get_thread_id(app, chat_id):
    async with aiosqlite.connect(DATABASE) as db:
        async with db.execute("SELECT thread_id FROM user_threads WHERE chat_id = ?", (chat_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return row[0]
            else:
                thread_id = await create_thread(app)
                if thread_id:
                    await db.execute("INSERT INTO user_threads (chat_id, thread_id) VALUES (?, ?)", (chat_id, thread_id))
                    await db.commit()

                    # Читаем начальное сообщение из файла
                    if not os.path.exists("first_message.txt"):
                        logger.error("Файл first_message.txt не найден. Использую сообщение по умолчанию.")
                        initial_message = "Здравствуйте! Чем могу помочь?"
                    else:
                        async with aiofiles.open("first_message.txt", "r", encoding="utf-8") as f:
                            initial_message = (await f.read()).strip()
                            if not initial_message:
                                logger.warning("Файл first_message.txt пуст. Использую сообщение по умолчанию.")
                                initial_message = "Здравствуйте! Чем могу помочь?"

                    # Добавляем в тред начальное сообщение в качестве системного (или можете выбрать другую роль)
                    await add_message_to_thread(thread_id, "assistant", initial_message)

                    logger.info(f"Создан новый тред {thread_id} для chat_id {chat_id}")
                    return thread_id
                else:
                    logger.error(f"Не удалось создать тред для chat_id: {chat_id}")
                    return None

async def process_message(app, chat_id, text):
    thread_id = await get_thread_id(app, chat_id)
    if not thread_id:
        logger.error(f"Не удалось получить или создать тред для chat_id: {chat_id}")
        return

    added_message = await add_message_to_thread(app, thread_id, "user", text)
    if not added_message:
        logger.error(f"Не удалось добавить сообщение пользователя '{text}' в тред {thread_id}")
        return

    run = await create_and_poll_run(app, thread_id)
    if not run:
        logger.error(f"Не удалось запустить ассистента для треда {thread_id}")
        return

    if run.get("status") == "completed":
        messages_list = run.get("messages", [])
        assistant_answer = extract_assistant_message(messages_list)
        if assistant_answer:
            logger.info(f"Получен ответ от ассистента для треда {thread_id}: {assistant_answer}")
            await send_wazzup24_message(app, chat_id, assistant_answer)
        else:
            logger.warning(f"Ответ от ассистента не найден для треда {thread_id}")
    else:
        logger.warning(f"Run not completed для треда {thread_id}, статус: {run.get('status')}")

async def handle_webhook(request):
    try:
        data = await request.json()
    except Exception as e:
        logger.error(f"Ошибка при парсинге JSON: {e}")
        return web.json_response({"status": "invalid json"}, status=400)

    if not data:
        return web.json_response({"status": "no data"}, status=200)

    messages = data.get("messages", [])
    if not messages:
        return web.json_response({"status": "no messages"}, status=200)

    tasks = []
    for msg in messages:
        chat_id = msg.get("chatId")
        text = msg.get("text", "")

        if chat_id and text:
            logger.info(f"Получено сообщение от {chat_id}: {text}")
            tasks.append(process_message(request.app, chat_id, text))
        else:
            logger.warning(f"Сообщение без текста или chatId: {msg}")

    if tasks:
        await asyncio.gather(*tasks)

    return web.json_response({"status": "ok"}, status=200)

async def init_app():
    # Создаём приложение и клиентскую сессию внутри event loop
    app = web.Application()
    app["client_session"] = ClientSession()
    app.router.add_post('/webhook', handle_webhook)
    return app

def main():
    # Сначала запускаем create_assistant.py
    result = subprocess.run([sys.executable, "create_assistant.py"], capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"Не удалось запустить create_assistant.py: {result.stderr}")
        return

    # После запуска create_assistant.py должен быть ASSISTANT_ID
    load_dotenv()
    assistant_id = os.getenv("ASSISTANT_ID")
    if not assistant_id:
        logger.error("ASSISTANT_ID не найден после запуска create_assistant.py")
        return

    create_database()
    # Создаём event loop и запускаем init_app
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app = loop.run_until_complete(init_app())

    web.run_app(app, host='0.0.0.0', port=5000)

if __name__ == '__main__':
    main()
