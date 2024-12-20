import os
from dotenv import load_dotenv
from openai import OpenAI

# Загружаем переменные окружения из .env
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ASSISTANT_ID = os.getenv("ASSISTANT_ID")

if not OPENAI_API_KEY:
    raise EnvironmentError("OPENAI_API_KEY не найден в файле .env")

# Проверяем, есть ли уже ID ассистента
if ASSISTANT_ID:
    print(f"ASSISTANT_ID уже существует: {ASSISTANT_ID}. Создавать нового ассистента не нужно.")
else:
    # Если ASSISTANT_ID не найден, создаём нового ассистента
    if not os.path.exists("waprompt.txt"):
        raise FileNotFoundError("Файл waprompt.txt не найден")

    with open("waprompt.txt", "r", encoding="utf-8") as f:
        instructions = f.read().strip()

    # Инициализируем OpenAI клиент
    client = OpenAI(api_key=OPENAI_API_KEY)

    # Создаём ассистента
    assistant = client.beta.assistants.create(
        name="My Custom Assistant",
        instructions=instructions,
        tools=[],
        model="gpt-4o-mini"
    )

    new_assistant_id = assistant.id
    print(f"Ассистент создан с id: {new_assistant_id}")

    # Добавляем ASSISTANT_ID в .env
    env_path = ".env"
    lines = []

    # Считываем существующий .env, если он есть
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as env_file:
            lines = env_file.readlines()

    # Добавляем в конец файла ASSISTANT_ID
    lines.append(f"ASSISTANT_ID={new_assistant_id}\n")

    # Перезаписываем .env
    with open(env_path, "w", encoding="utf-8") as env_file:
        env_file.writelines(lines)

    print("ASSISTANT_ID успешно сохранён в .env.")
