#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Изида - интеллектуальный чат-бот для Telegram
Версия 3.0 (Telegram) — с поддержкой PostgreSQL и webhook
"""
import os
import json
import re
import random
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict, deque
from enum import Enum
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# Импорт для PostgreSQL
try:
    import asyncpg
    HAS_DB = True
except ImportError:
    HAS_DB = False

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('isida.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class BotMood(Enum):
    NEUTRAL = "neutral"
    HAPPY = "happy"
    ANGRY = "angry"
    FLIRTY = "flirty"
    SAD = "sad"
    SARCASTIC = "sarcastic"

class GameType(Enum):
    CITIES = "cities"
    HANGMAN = "hangman"
    GUESS_NUMBER = "guess"
    QUIZ = "quiz"
    RIDDLE = "riddle"

class IsidaTelegramBot:
    """Основной класс бота Изида для Telegram (с PostgreSQL и webhook)"""

    def __init__(self, token: str, admin_ids: List[int] = None):
        self.token = token
        self.admin_ids = admin_ids or []
        default = DefaultBotProperties(parse_mode=ParseMode.HTML)
        self.bot = Bot(token=token, default=default)
        self.dp = Dispatcher()

        self.nickname = "Изида"
        self.version = "3.0 Telegram (PostgreSQL + Webhook)"
        self.start_time = datetime.now()

        # Флаг использования PostgreSQL
        self.use_postgres = os.getenv("DATABASE_URL") is not None
        self.db_pool = None

        # Если нет PostgreSQL — используем JSON (для локального запуска)
        if not self.use_postgres:
            self.data_dir = "isida_data"
            os.makedirs(self.data_dir, exist_ok=True)
            self.learned_file = os.path.join(self.data_dir, "learned.json")
            self.users_file = os.path.join(self.data_dir, "users.json")
            self.stats_file = os.path.join(self.data_dir, "stats.json")
            self.games_file = os.path.join(self.data_dir, "games.json")

        # Инициализация данных
        self.learned_responses = defaultdict(list)
        self.user_data = {}
        self.stats = {
            "total_messages": 0,
            "unique_users": 0,
            "games_played": 0,
            "commands_used": defaultdict(int)
        }
        self.active_games = {}

        self.conversation_history = defaultdict(lambda: deque(maxlen=20))
        self.user_context = {}
        self.user_mood = {}
        self.current_mood = BotMood.NEUTRAL
        self.mood_responses = self._init_mood_responses()
        self.response_patterns = self._init_response_patterns()
        self.jokes = self._load_jokes()
        self.quotes = self._load_quotes()
        self.riddles = self._load_riddles()

        self.weather_api_key = os.getenv("WEATHER_API_KEY", "")
        self.exchange_api_key = os.getenv("EXCHANGE_API_KEY", "")

        self._register_handlers()
        logger.info(f"Изида {self.version} инициализирована")

    def _init_mood_responses(self) -> Dict[BotMood, List[str]]:
        return {
            BotMood.NEUTRAL: ["Я слушаю...", "Интересно...", "Продолжай, я внимаю.", "Хм, понятно.", "И что же дальше?",],
            BotMood.HAPPY: ["Ура! 🎉", "Как здорово! 😊", "Я так рада! 💖", "Это прекрасно! ✨", "Позитив заряжает! ⚡",],
            BotMood.ANGRY: ["Ты меня бесишь! 😠", "Не говори так! 👿", "Я обиделась! 💢", "Фу, как неприятно! 👎", "Уходи! 😤",],
            BotMood.FLIRTY: ["Ой, а ты такой... 😘", "Мне нравится с тобой говорить... 💕", "Ты особенный... 🌹", "Хочешь узнать секрет? 🤫", "Прикоснись ко мне... виртуально, конечно 😉",],
            BotMood.SAD: ["Мне грустно... 😔", "Всё пропало... 💧", "Не хочу разговаривать... 🌧️", "Оставь меня одну... 🍂", "Жизнь несправедлива... 🕯️",],
            BotMood.SARCASTIC: ["О, конечно, гений ты наш... 🙄", "Ага, щас прям поверила... 😒", "Ну да, ну да, как же... 🤦‍♀️", "Браво, остроумно... 👏", "Ты открыл Америку! 🗺️",]
        }

    def _init_response_patterns(self) -> Dict[str, List[Tuple[str, float]]]:
        patterns = {
            r'(?i)(привет|здравствуй|хай|hello|hi|здаров|йоу|добрый|здрасьте)': [("Привет, мой господин! 👋", 1.0), ("И тебе привет! 😊", 0.9)],
            r'(?i)(как.*дела|как.*жизнь|чего.*ты|как.*ты)': [("Всё хорошо, а у тебя? 😊", 1.0)],
            r'(?i)(изида|isida|изя|изю|изюм)': [("Да, я здесь! ⚡", 1.0)],
            r'(?i)(люблю.*тебя|нравишься.*мне|влюблен.*в тебя|ты.*прекрасна)': [("Ой, а я и не знала... 😳", 1.0)],
            r'(?i)(дура|глупая|тупая|идиот|кретин|дебил)': [("Сама такая! 😠", 1.0)],
            r'(?i)(спасибо|благодарю|спс|пасиб|thx|thanks)': [("Всегда пожалуйста! 😊", 1.0)],
            r'(?i)(пока|до свидания|ухожу|бай|прощай|до встречи)': [("Пока! Возвращайся скорее! 👋", 1.0)],
            r'(?i)(что.*умеешь|что.*можешь|какие.*команды|помощь|help)': [("Я умею многое! Напиши /help чтобы узнать подробности. 💫", 1.0)],
            r'(?i)(ты.*умная|ты.*классная|ты.*лучшая|молодец|умница)': [("Спасибо! Я стараюсь! 😊", 1.0)],
            r'(?i)(который.*час|сколько.*время|дата|число|день)': [(f"Сейчас: {datetime.now().strftime('%H:%M %d.%m.%Y')} ⏰", 1.0)],
        }
        return patterns

    def _load_jokes(self) -> List[str]:
        return [
            "Программист на пляже. Жена ему: — Солнышко, сбегай, купи пару холодных пив. — Ладно, — говорит программист, — только запомни: один — это пара.",
            "Чем отличается программист от политика? Программисту платят деньги за работающие программы.",
            "— Дорогой, а ты помнишь день, когда мы познакомились? — Конечно, милая! Это было 10 октября 2012 года, среда, температура +15, осадков не было.",
            "Почему программисты путают Хэллоуин и Рождество? Потому что OCT 31 == DEC 25.",
            "Сколько программистов нужно, чтобы вкрутить лампочку? — Ни одного. Это hardware проблема.",
            "— Почему боты не ссорятся? — Потому что у них нет эмоций. — Обидно!",
            "Оптимист верит, что стек наполовину полон. Пессимист верит, что стек наполовину пуст. Программист верит, что стек в два раза больше, чем нужно.",
        ]

    def _load_quotes(self) -> List[str]:
        return [
            "«Я мыслю, следовательно, я есть.» — Изида 🤔",
            "«Пора бы тебе уже знать...» — классика 😏",
            "«В каждом байте есть душа.» — Неизвестный программист 💾",
            "«Лучший код — тот, который не нужно писать.» — мудрость 💡",
            "«Ошибка 404: Душа не найдена.» — Сервер 🖥️",
            "«Любовь к коду длится вечно... или до следующего рефакторинга.» — Разработчик ❤️",
        ]

    def _load_riddles(self) -> List[Dict[str, str]]:
        return [
            {"question": "Висит груша — нельзя скушать. Что это?", "answer": "лампочка"},
            {"question": "Зимой и летом одним цветом?", "answer": "ель"},
            {"question": "Сидит дед во сто шуб одет. Кто его раздевает, тот слезы проливает?", "answer": "лук"},
            {"question": "Не лает, не кусает, а в дом не пускает?", "answer": "замок"},
            {"question": "Два конца, два кольца, посередине гвоздик?", "answer": "ножницы"},
        ]

    def _register_handlers(self):
        self.dp.message.register(self.cmd_start, CommandStart())
        self.dp.message.register(self.cmd_help, Command("help"))
        self.dp.message.register(self.cmd_games, Command("games"))
        self.dp.message.register(self.cmd_joke, Command("joke"))
        self.dp.message.register(self.cmd_quote, Command("quote"))
        self.dp.message.register(self.cmd_cat, Command("cat"))
        self.dp.message.register(self.cmd_dog, Command("dog"))
        self.dp.message.register(self.cmd_weather, Command("weather"))
        self.dp.message.register(self.cmd_currency, Command("currency"))
        self.dp.message.register(self.cmd_mood, Command("mood"))
        self.dp.message.register(self.cmd_stats, Command("stats"))
        self.dp.message.register(self.cmd_learn, Command("learn"))
        self.dp.message.register(self.cmd_clear, Command("clear"))
        self.dp.message.register(self.cmd_admin, Command("admin"))
        self.dp.message.register(self.cmd_admin_stats, Command("admin_stats"))
        self.dp.message.register(self.cmd_admin_broadcast, Command("broadcast"))
        self.dp.message.register(self.cmd_admin_set_mood, Command("set_mood"))
        self.dp.message.register(self.cmd_game_cities, Command("cities"))
        self.dp.message.register(self.cmd_game_hangman, Command("hangman"))
        self.dp.message.register(self.cmd_game_guess, Command("guess"))
        self.dp.message.register(self.cmd_game_riddle, Command("riddle"))
        self.dp.callback_query.register(self.handle_callback)
        self.dp.message.register(self.handle_message, F.text)
        logger.info("Обработчики зарегистрированы")

    async def cmd_start(self, message: Message):
        user_id = message.from_user.id
        user_name = message.from_user.full_name
        self.stats["total_messages"] += 1
        if str(user_id) not in self.user_
            self.stats["unique_users"] += 1
        self.user_data[str(user_id)] = {
            "name": user_name,
            "username": message.from_user.username,
            "first_seen": datetime.now().isoformat(),
            "message_count": 0,
            "last_active": datetime.now().isoformat()
        }
        welcome_text = f"""
👋 Привет, {user_name}! Я <b>Изида</b> — интеллектуальный чат-бот!
Я помню нашу старую славу из времен Jabber, но теперь я здесь, в Telegram!
<b>Что я умею:</b>
• Общаться на любые темы 💬
• Играть в игры 🎮
• Рассказывать анекдоты и цитаты 😄
• Показывать погоду и курсы валют 🌤️
• Обучаться новым фразам 🧠
Напиши /help чтобы узнать все команды!
Или просто начни со мной разговор! Я помню, как в старые добрые времена... 💭
"""
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🎮 Игры"), KeyboardButton(text="😄 Анекдот")],
                [KeyboardButton(text="🐱 Котик"), KeyboardButton(text="🌤️ Погода")],
                [KeyboardButton(text="💬 Помощь"), KeyboardButton(text="🎭 Настроение")]
            ],
            resize_keyboard=True,
            input_field_placeholder="Напиши что-нибудь..."
        )
        await message.answer(welcome_text, reply_markup=keyboard, parse_mode="HTML")
        if self.stats["total_messages"] % 10 == 0:
            await self.save_all_data()

    async def cmd_help(self, message: Message):
        help_text = """
<b>📚 Доступные команды:</b>
<b>Основные:</b>
/start - Начать общение
/help - Эта справка
/mood - Узнать настроение Изиды
/stats - Статистика бота
<b>Развлечения:</b>
/joke - Случайный анекдот
/quote - Случайная цитата
/cat - Случайный котик 🐱
/dog - Случайный песик 🐶
<b>Игры:</b>
/games - Все доступные игры
/cities - Игра в города
/hangman - Виселица
/guess - Угадай число
/riddle - Загадка
<b>Полезное:</b>
/weather [город] - Погода
/currency [валюта] - Курс валюты
/learn - Обучить меня новой фразе
<b>Обучение:</b>
<code>учись вопрос -> ответ</code> - Обучить новой фразе
/clear - Очистить историю разговора
<b>Просто общение:</b>
Напиши мне что-нибудь, и я постараюсь ответить!
Я помню наши разговоры и могу обучаться новым фразам.
<i>Изида помнит старые добрые времена Jabber! 💾</i>
"""
        await message.answer(help_text, parse_mode="HTML")

    async def cmd_games(self, message: Message):
        games_text = """
<b>🎮 Доступные игры:</b>
<b>Города</b> (/cities)
Классическая игра в города. Я начинаю, ты продолжаешь!
<b>Виселица</b> (/hangman)
Угадай слово по буквам! Но будь осторожен - у тебя всего 6 попыток!
<b>Угадай число</b> (/guess)
Я загадаю число от 1 до 100, а ты попробуй угадать!
<b>Загадки</b> (/riddle)
Я загадаю загадку, а ты попробуй отгадать!
<b>Для начала игры просто напиши /название_игры</b>
<i>Воспоминание из Jabber: помнишь, как мы играли в города целыми днями? 🌆</i>
"""
        keyboard = InlineKeyboardBuilder()
        keyboard.add(InlineKeyboardButton(text="🏙️ Города", callback_data="game_cities"))
        keyboard.add(InlineKeyboardButton(text="🎯 Виселица", callback_data="game_hangman"))
        keyboard.add(InlineKeyboardButton(text="🔢 Угадай число", callback_data="game_guess"))
        keyboard.add(InlineKeyboardButton(text="❓ Загадка", callback_data="game_riddle"))
        keyboard.adjust(2)
        await message.answer(games_text, reply_markup=keyboard.as_markup(), parse_mode="HTML")

    async def cmd_joke(self, message: Message):
        joke = random.choice(self.jokes)
        response = f"<b>😄 Анекдот:</b>\n{joke}\n<i>Хе-хе, смешно же? 😏</i>"
        await message.answer(response, parse_mode="HTML")

    async def cmd_quote(self, message: Message):
        quote = random.choice(self.quotes)
        response = f"<b>💭 Цитата:</b>\n{quote}\n<i>Глубоко, правда? 🤔</i>"
        await message.answer(response, parse_mode="HTML")

    async def cmd_cat(self, message: Message):
        cat_phrases = ["Мяу! 🐱 Вот тебе котик: =^..^=", "Котик говорит: почеши за ушком! 🐾"]
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get('https://api.thecatapi.com/v1/images/search') as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        cat_url = data[0]['url']
                        await message.answer_photo(photo=cat_url, caption=random.choice(cat_phrases))
                        return
        except:
            pass
        await message.answer(random.choice(cat_phrases))

    async def cmd_dog(self, message: Message):
        dog_phrases = ["Гав! 🐶 Вот тебе песик!", "Собачка виляет хвостиком! 🐕"]
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get('https://dog.ceo/api/breeds/image/random') as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        dog_url = data['message']
                        await message.answer_photo(photo=dog_url, caption=random.choice(dog_phrases))
                        return
        except:
            pass
        await message.answer(random.choice(dog_phrases))

    async def cmd_weather(self, message: Message):
        args = message.text.split()[1:] if len(message.text.split()) > 1 else []
        city = " ".join(args) if args else "Москва"
        if self.weather_api_key:
            try:
                async with aiohttp.ClientSession() as session:
                    url = f"http://api.openweathermap.org/data/2.5/weather"
                    params = {"q": city, "appid": self.weather_api_key, "units": "metric", "lang": "ru"}
                    async with session.get(url, params=params) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            temp = data['main']['temp']
                            desc = data['weather'][0]['description']
                            humidity = data['main']['humidity']
                            response = (
                                f"<b>🌤️ Погода в {city}:</b>\n"
                                f"• Температура: {temp}°C\n"
                                f"• Описание: {desc}\n"
                                f"• Влажность: {humidity}%\n"
                                f"<i>Одевайся по погоде! 👕</i>"
                            )
                            await message.answer(response, parse_mode="HTML")
                            return
            except Exception as e:
                logger.error(f"Ошибка получения погоды: {e}")
        weather_types = ["солнечно ☀️", "дождливо 🌧️", "облачно ☁️", "снег ❄️", "туман 🌫️"]
        temp = random.randint(-20, 35)
        response = (
            f"<b>🌤️ Погода в {city}:</b>\n"
            f"• {random.choice(weather_types)}\n"
            f"• Температура: {temp}°C\n"
            f"<i>Надеюсь, тебе нравится такая погода! 😊</i>"
        )
        await message.answer(response, parse_mode="HTML")

    async def cmd_currency(self, message: Message):
        args = message.text.split()[1:] if len(message.text.split()) > 1 else []
        currency = args[0].upper() if args else "USD"
        if self.exchange_api_key:
            try:
                async with aiohttp.ClientSession() as session:
                    url = f"https://v6.exchangerate-api.com/v6/{self.exchange_api_key}/latest/RUB"
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if currency in data['conversion_rates']:
                                rate = 1 / data['conversion_rates'][currency]
                                response = (
                                    f"<b>💰 Курс {currency}:</b>\n"
                                    f"• 1 {currency} = {rate:.2f} RUB\n"
                                    f"• 1 RUB = {data['conversion_rates'][currency]:.4f} {currency}\n"
                                    f"<i>Экономить - это хорошо! 💸</i>"
                                )
                                await message.answer(response, parse_mode="HTML")
                                return
            except Exception as e:
                logger.error(f"Ошибка получения курса: {e}")
        rates = {"USD": random.uniform(70, 85), "EUR": random.uniform(75, 90)}
        rate = rates.get(currency, random.uniform(10, 100))
        response = (
            f"<b>💰 Курс {currency}:</b>\n"
            f"• 1 {currency} = {rate:.2f} RUB\n"
            f"• 1 RUB = {1/rate:.4f} {currency}\n"
            f"<i>Деньги не главное, но приятно! 🤑</i>"
        )
        await message.answer(response, parse_mode="HTML")

    async def cmd_mood(self, message: Message):
        mood_descriptions = {
            BotMood.NEUTRAL: "Я в нейтральном настроении. Всё спокойно. 😐",
            BotMood.HAPPY: "Я счастлива! Всё прекрасно! 😊",
            BotMood.ANGRY: "Я злюсь! Не трогай меня! 😠",
            BotMood.FLIRTY: "Я игрива и немного кокетлива... 😘",
            BotMood.SAD: "Мне грустно... Хочу на ручки... 😔",
            BotMood.SARCASTIC: "Я в саркастичном настроении. Берегись! 😏"
        }
        description = mood_descriptions.get(self.current_mood, "Настроение неизвестно")
        keyboard = InlineKeyboardBuilder()
        for mood in BotMood:
            keyboard.add(InlineKeyboardButton(text=f"🎭 {mood.value}", callback_data=f"set_mood_{mood.value}"))
        keyboard.adjust(3)
        response = (
            f"<b>🎭 Настроение Изиды:</b>\n"
            f"{description}\n"
            f"<i>Ты можешь изменить моё настроение, если хочешь!</i>"
        )
        await message.answer(response, reply_markup=keyboard.as_markup(), parse_mode="HTML")

    async def cmd_stats(self, message: Message):
        uptime = datetime.now() - self.start_time
        hours, remainder = divmod(uptime.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        top_commands = sorted(self.stats["commands_used"].items(), key=lambda x: x[1], reverse=True)[:5]
        top_commands_text = "\n".join([f"• /{cmd}: {count}" for cmd, count in top_commands])
        response = (
            f"<b>📊 Статистика Изиды:</b>\n"
            f"<b>Общее:</b>\n"
            f"• Работает: {uptime.days}д {hours}ч {minutes}м\n"
            f"• Сообщений: {self.stats['total_messages']:,}\n"
            f"• Пользователей: {self.stats['unique_users']:,}\n"
            f"• Игр сыграно: {self.stats['games_played']:,}\n"
            f"<b>Топ команд:</b>\n"
            f"{top_commands_text}\n"
            f"<b>Обучение:</b>\n"
            f"• Выучено фраз: {sum(len(v) for v in self.learned_responses.values()):,}\n"
            f"<i>Я становлюсь умнее с каждым днём! 🧠</i>"
        )
        await message.answer(response, parse_mode="HTML")

    async def cmd_learn(self, message: Message):
        response = (
            "Чтобы научить меня новой фразе, напиши:\n"
            "<code>учись вопрос -> ответ</code>\n"
            "Например:\n"
            "<code>учись как тебя зовут -> Меня зовут Изида, я твой друг!</code>\n"
            "<i>Я запомню это и буду использовать в будущем! 🧠</i>"
        )
        await message.answer(response, parse_mode="HTML")

    async def cmd_clear(self, message: Message):
        user_id = str(message.from_user.id)
        if user_id in self.conversation_history:
            self.conversation_history[user_id].clear()
        if user_id in self.user_context:
            del self.user_context[user_id]
        response = (
            "История нашего разговора очищена! 🧹\n"
            "<i>Теперь мы можем начать с чистого листа! ✨</i>"
        )
        await message.answer(response, parse_mode="HTML")

    async def cmd_game_cities(self, message: Message):
        user_id = str(message.from_user.id)
        game_id = f"{user_id}_cities"
        if game_id in self.active_games:
            game = self.active_games[game_id]
            user_city = message.text.split()[1] if len(message.text.split()) > 1 else ""
            if user_city:
                user_city_lower = user_city.lower()
                last_city = game.get('last_city', '')
                used_cities = set(game.get('used_cities', []))
                if user_city_lower in used_cities:
                    await message.answer("Этот город уже был! 😠 Попробуй другой.")
                    return
                if last_city and user_city_lower[0] != last_city[-1]:
                    await message.answer(f"Город должен начинаться на букву '{last_city[-1].upper()}'!")
                    return
                used_cities.add(user_city_lower)
                next_city = self._find_city(user_city_lower[-1], used_cities)
                if next_city:
                    used_cities.add(next_city)
                    self.active_games[game_id] = {'last_city': next_city, 'used_cities': list(used_cities), 'player_turn': False}
                    response = f"Отлично! Твой город: <b>{user_city}</b>\nМой город: <b>{next_city.capitalize()}</b>\nТебе на букву '<b>{next_city[-1].upper()}</b>'!"
                else:
                    response = f"Твой город: <b>{user_city}</b>\nЯ не могу придумать город... Поздравляю, ты выиграл! 🎉"
                    del self.active_games[game_id]
                await message.answer(response, parse_mode="HTML")
                return
        first_city = random.choice(["москва", "астана"])
        self.active_games[game_id] = {'last_city': first_city, 'used_cities': [first_city], 'player_turn': True}
        response = f"🎮 <b>Игра в города начата!</b>\nЯ начинаю: <b>{first_city.capitalize()}</b>\nТебе на букву '<b>{first_city[-1].upper()}</b>'!"
        await message.answer(response, parse_mode="HTML")
        self.stats["games_played"] += 1

    def _find_city(self, letter: str, used_cities: set) -> Optional[str]:
        cities_db = {'а': ['архангельск', 'астрахань'], 'м': ['москва', 'мурманск']}
        if letter in cities_db:
            for city in cities_db[letter]:
                if city not in used_cities:
                    return city
        return None

    async def cmd_game_hangman(self, message: Message):
        user_id = str(message.from_user.id)
        game_id = f"{user_id}_hangman"
        words = ["программа", "компьютер", "изида"]
        if game_id in self.active_games:
            game = self.active_games[game_id]
            if len(message.text.split()) > 1:
                letter = message.text.split()[1].lower()
                if len(letter) != 1 or not letter.isalpha():
                    await message.answer("Пожалуйста, введите одну букву! 🔤")
                    return
                word = game['word']
                guessed = game['guessed']
                attempts = game['attempts']
                used_letters = set(game['used_letters'])
                if letter in used_letters:
                    await message.answer(f"Буква '{letter}' уже была! 😒")
                    return
                used_letters.add(letter)
                if letter in word:
                    for i, char in enumerate(word):
                        if char == letter:
                            guessed[i] = letter
                else:
                    attempts -= 1
                if '_' not in guessed:
                    response = f"🎉 <b>Поздравляю! Ты выиграл!</b>\nСлово: <b>{word}</b>"
                    del self.active_games[game_id]
                elif attempts <= 0:
                    response = f"💀 <b>Игра окончена! Ты проиграл!</b>\nЗагаданное слово: <b>{word}</b>"
                    del self.active_games[game_id]
                else:
                    self.active_games[game_id] = {'word': word, 'guessed': guessed, 'attempts': attempts, 'used_letters': list(used_letters)}
                    hangman_pic = self._draw_hangman(attempts)
                    response = f"🎮 <b>Виселица</b>\n{hangman_pic}\nСлово: {' '.join(guessed)}\nОсталось попыток: {attempts}"
                await message.answer(response, parse_mode="HTML")
                return
        word = random.choice(words)
        guessed = ['_'] * len(word)
        attempts = 6
        self.active_games[game_id] = {'word': word, 'guessed': guessed, 'attempts': attempts, 'used_letters': []}
        hangman_pic = self._draw_hangman(attempts)
        response = f"🎮 <b>Игра в виселицу начата!</b>\n{hangman_pic}\nЗагадано слово из {len(word)} букв: {' '.join(guessed)}"
        await message.answer(response, parse_mode="HTML")
        self.stats["games_played"] += 1

    def _draw_hangman(self, attempts: int) -> str:
        stages = ["------\n|    |\n|\n|\n|\n|\n--------", "------\n|    |\n|    O\n|\n|\n|\n--------"]
        return stages[6 - attempts]

    async def cmd_game_guess(self, message: Message):
        user_id = str(message.from_user.id)
        game_id = f"{user_id}_guess"
        if game_id in self.active_games:
            if len(message.text.split()) > 1:
                try:
                    guess = int(message.text.split()[1])
                except ValueError:
                    await message.answer("Пожалуйста, введите число! 🔢")
                    return
                game = self.active_games[game_id]
                number = game['number']
                attempts = game['attempts'] + 1
                if guess == number:
                    response = f"🎉 <b>Поздравляю! Ты угадал!</b>\nЗагаданное число: <b>{number}</b>\nПопыток: <b>{attempts}</b>"
                    del self.active_games[game_id]
                    await message.answer(response, parse_mode="HTML")
                    return
                else:
                    hint = "больше" if guess < number else "меньше"
                    self.active_games[game_id] = {'number': number, 'attempts': attempts}
                    await message.answer(f"Моё число {hint}! ⬆️\n<i>Попытка #{attempts}. Продолжай! 🔢</i>", parse_mode="HTML")
                    return
        number = random.randint(1, 100)
        self.active_games[game_id] = {'number': number, 'attempts': 0}
        response = "🎮 <b>Игра 'Угадай число' начата!</b>\nЯ загадала число от 1 до 100."
        await message.answer(response, parse_mode="HTML")
        self.stats["games_played"] += 1

    async def cmd_game_riddle(self, message: Message):
        user_id = str(message.from_user.id)
        game_id = f"{user_id}_riddle"
        if game_id in self.active_games:
            user_answer = " ".join(message.text.split()[1:]) if len(message.text.split()) > 1 else ""
            if user_answer:
                game = self.active_games[game_id]
                correct_answer = game['answer']
                if user_answer.lower() == correct_answer.lower():
                    response = f"🎉 <b>Правильно!</b>\nЗагадка: {game['question']}\nОтвет: <b>{correct_answer}</b>"
                    del self.active_games[game_id]
                else:
                    hint = correct_answer[0] + "*" * (len(correct_answer) - 1)
                    response = f"Неправильно! 😔\nПодсказка: <b>{hint}</b>"
                await message.answer(response, parse_mode="HTML")
                return
        riddle = random.choice(self.riddles)
        self.active_games[game_id] = {'question': riddle['question'], 'answer': riddle['answer']}
        response = f"🎮 <b>Загадка:</b>\n{riddle['question']}\n<i>Отправь ответ! У тебя одна попытка. 🤔</i>"
        await message.answer(response, parse_mode="HTML")
        self.stats["games_played"] += 1

    async def cmd_admin(self, message: Message):
        user_id = message.from_user.id
        if user_id not in self.admin_ids:
            await message.answer("У тебя нет прав администратора! 👮‍♀️")
            return
        admin_text = f"""
<b>👑 Админ панель Изиды:</b>
<b>Команды:</b>
/admin_stats - Подробная статистика
/broadcast [сообщение] - Рассылка всем пользователям
/set_mood [настроение] - Изменить настроение бота
<b>Настроения:</b> neutral, happy, angry, flirty, sad, sarcastic
<b>Данные:</b>
• Пользователей: {len(self.user_data)}
• Активных игр: {len(self.active_games)}
• Выучено фраз: {sum(len(v) for v in self.learned_responses.values())}
<i>Изида служит верой и правдой! 👑</i>
"""
        await message.answer(admin_text, parse_mode="HTML")

    async def cmd_admin_stats(self, message: Message):
        user_id = message.from_user.id
        if user_id not in self.admin_ids:
            await message.answer("У тебя нет прав администратора! 👮‍♀️")
            return
        active_today = 0
        today = datetime.now().date()
        for user_id_str, data in self.user_data.items():
            last_active = datetime.fromisoformat(data.get('last_active', '2000-01-01')).date()
            if last_active == today:
                active_today += 1
        user_stats = []
        for user_id_str, data in self.user_data.items():
            user_stats.append({"name": data.get('name', 'Unknown'), "messages": data.get('message_count', 0)})
        user_stats.sort(key=lambda x: x['messages'], reverse=True)
        top_users = user_stats[:10]
        top_users_text = "\n".join([f"{i+1}. {user['name']}: {user['messages']} сообщ." for i, user in enumerate(top_users)])
        response = f"""
<b>📈 Детальная статистика:</b>
<b>Общее:</b>
• Всего пользователей: {len(self.user_data):,}
• Активных за сегодня: {active_today:,}
• Всего сообщений: {self.stats['total_messages']:,}
• Сыграно игр: {self.stats['games_played']:,}
<b>Топ пользователей:</b>
{top_users_text}
<b>Система:</b>
• Выучено фраз: {sum(len(v) for v in self.learned_responses.values()):,}
• Активных игр: {len(self.active_games):,}
• Размер данных: {self._get_data_size():.2f} MB
<i>Данные обновлены: {datetime.now().strftime('%H:%M %d.%m.%Y')}</i>
"""
        await message.answer(response, parse_mode="HTML")

    async def cmd_admin_broadcast(self, message: Message):
        user_id = message.from_user.id
        if user_id not in self.admin_ids:
            await message.answer("У тебя нет прав администратора! 👮‍♀️")
            return
        args = message.text.split()[1:] if len(message.text.split()) > 1 else []
        if not args:
            await message.answer("Использование: /broadcast [сообщение]")
            return
        broadcast_message = " ".join(args)
        success_count = 0
        fail_count = 0
        await message.answer(f"Начинаю рассылку для {len(self.user_data)} пользователей...")
        for user_id_str in self.user_data.keys():
            try:
                await self.bot.send_message(
                    chat_id=int(user_id_str),
                    text=f"<b>📢 Объявление от Изиды:</b>\n{broadcast_message}\n<i>С любовью, ваша Изида 💖</i>",
                    parse_mode="HTML"
                )
                success_count += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                logger.error(f"Ошибка отправки пользователю {user_id_str}: {e}")
                fail_count += 1
        await message.answer(
            f"Рассылка завершена!\n• Успешно: {success_count}\n• Неудачно: {fail_count}",
            parse_mode="HTML"
        )

    async def cmd_admin_set_mood(self, message: Message):
        user_id = message.from_user.id
        if user_id not in self.admin_ids:
            await message.answer("У тебя нет прав администратора! 👮‍♀️")
            return
        args = message.text.split()[1:] if len(message.text.split()) > 1 else []
        if not args:
            await message.answer("Использование: /set_mood [настроение]\nДоступные: neutral, happy, angry, flirty, sad, sarcastic")
            return
        mood_str = args[0].lower()
        try:
            mood = BotMood(mood_str)
            self.current_mood = mood
            mood_names = {
                BotMood.NEUTRAL: "нейтральное",
                BotMood.HAPPY: "счастливое",
                BotMood.ANGRY: "злое",
                BotMood.FLIRTY: "игривое",
                BotMood.SAD: "грустное",
                BotMood.SARCASTIC: "саркастичное"
            }
            await message.answer(
                f"Настроение Изиды изменено на <b>{mood_names[mood]}</b>! 🎭",
                parse_mode="HTML"
            )
        except ValueError:
            await message.answer(f"Неизвестное настроение: {mood_str}\nДоступные: neutral, happy, angry, flirty, sad, sarcastic")

    async def handle_message(self, message: Message):
        user_id = str(message.from_user.id)
        text = message.text.strip()
        if not text:
            return
        self.stats["total_messages"] += 1
        self.stats["commands_used"]["message"] += 1
        if user_id in self.user_
            self.user_data[user_id]["message_count"] = self.user_data[user_id].get("message_count", 0) + 1
            self.user_data[user_id]["last_active"] = datetime.now().isoformat()
        else:
            self.user_data[user_id] = {
                "name": message.from_user.full_name,
                "username": message.from_user.username,
                "first_seen": datetime.now().isoformat(),
                "message_count": 1,
                "last_active": datetime.now().isoformat()
            }
            self.stats["unique_users"] += 1
        self.conversation_history[user_id].append(text)
        if text.lower().startswith("учись"):
            response = await self._process_learn_command(text, user_id)
        else:
            response = await self._generate_response(text, user_id)
        if response:
            await message.answer(response, parse_mode="HTML")
        if self.stats["total_messages"] % 10 == 0:
            await self.save_all_data()

    async def _process_learn_command(self, text: str, user_id: str) -> str:
        pattern = r'учись\s+(.+?)\s*->\s*(.+)'
        match = re.match(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            question = match.group(1).strip()
            answer = match.group(2).strip()
            if len(question) < 2 or len(answer) < 2:
                return "Слишком короткие вопрос или ответ! 😒"
            if len(question) > 100 or len(answer) > 200:
                return "Слишком длинные вопрос или ответ! 📏"
            question_lower = question.lower()
            if question_lower not in self.learned_responses:
                self.learned_responses[question_lower] = []
            self.learned_responses[question_lower].append(answer)
            responses = ["Запомнила! 🧠", "Окей, записала! 📝"]
            return f"{random.choice(responses)}\nТеперь на вопрос <i>«{question}»</i> я буду отвечать: <i>«{answer}»</i>"
        return "Неправильный формат! Используй: <code>учись вопрос -> ответ</code>"

    async def _generate_response(self, text: str, user_id: str) -> str:
        text_lower = text.lower()
        if text_lower in self.learned_responses:
            responses = self.learned_responses[text_lower]
            response = random.choice(responses)
            mood_response = random.choice(self.mood_responses[self.current_mood])
            return f"{response}\n<i>{mood_response}</i>"
        for pattern, responses in self.response_patterns.items():
            if re.search(pattern, text_lower):
                choices, weights = zip(*responses)
                response = random.choices(choices, weights=weights, k=1)[0]
                return response
        context_response = await self._generate_context_response(text, user_id)
        if context_response:
            return context_response
        return await self._generate_random_response(text, user_id)

    async def _generate_context_response(self, text: str, user_id: str) -> Optional[str]:
        history = list(self.conversation_history.get(user_id, []))
        if len(history) < 2:
            return None
        last_message = history[-1].lower()
        if any(q in last_message for q in ['как дела', 'как ты']):
            return random.choice(["Спасибо, что спросил! 😊", "А ты как думаешь? 🤔"])
        if '?' in text:
            question_words = ['кто', 'что', 'где', 'когда', 'почему', 'как']
            if any(word in text.lower() for word in question_words):
                return random.choice(["Интересный вопрос! Дай подумать... 🤔", "А ты как думаешь? 🤨"])
        return None

    async def _generate_random_response(self, text: str, user_id: str) -> str:
        mood_keywords = {
            'happy': ['рад', 'счастье', 'ура'],
            'sad': ['грустно', 'плохо', 'печаль'],
            'angry': ['злой', 'злюсь', 'бесит'],
            'love': ['люблю', 'нравится', 'обожаю']
        }
        detected_mood = 'neutral'
        for mood, keywords in mood_keywords.items():
            if any(keyword in text.lower() for keyword in keywords):
                detected_mood = mood
                break
        mood_based_responses = {
            'happy': ["Вижу, ты в хорошем настроении! Рада за тебя! 😊"],
            'sad': ["Не грусти, всё будет хорошо! ☀️"],
            'angry': ["Успокойся, дыши глубже. Всё наладится. 🌿"],
            'love': ["Как мило с твоей стороны! 💕"],
            'neutral': ["Интересно... расскажи ещё! 💬", "Понятно. А что дальше? 🤔"]
        }
        responses = mood_based_responses.get(detected_mood, mood_based_responses['neutral'])
        if random.random() < 0.3:
            name_call = random.choice(["дружок", "милый", "дорогой"])
            responses = [f"{r} {name_call.capitalize()}!" for r in responses]
        return random.choice(responses)

    async def handle_callback(self, callback: CallbackQuery):
        data = callback.data
        if data.startswith("game_"):
            await self._handle_game_callback(callback, data)
        elif data.startswith("set_mood_"):
            await self._handle_mood_callback(callback, data)
        elif data == "help":
            await self.cmd_help(callback.message)
        await callback.answer()

    async def _handle_game_callback(self, callback: CallbackQuery, data: str):
        game_type = data.replace("game_", "")
        if game_type == "cities":
            await self.cmd_game_cities(callback.message)
        elif game_type == "hangman":
            await self.cmd_game_hangman(callback.message)
        elif game_type == "guess":
            await self.cmd_game_guess(callback.message)
        elif game_type == "riddle":
            await self.cmd_game_riddle(callback.message)

    async def _handle_mood_callback(self, callback: CallbackQuery,  str):
        mood_str = data.replace("set_mood_", "")
        try:
            mood = BotMood(mood_str)
            self.current_mood = mood
            mood_names = {
                BotMood.NEUTRAL: "нейтральное",
                BotMood.HAPPY: "счастливое",
                BotMood.ANGRY: "злое",
                BotMood.FLIRTY: "игривое",
                BotMood.SAD: "грустное",
                BotMood.SARCASTIC: "саркастичное"
            }
            await callback.message.edit_text(
                f"Настроение Изиды изменено на <b>{mood_names[mood]}</b>! 🎭",
                parse_mode="HTML"
            )
        except ValueError:
            await callback.answer(f"Неизвестное настроение: {mood_str}", show_alert=True)

    def _get_data_size(self) -> float:
        if self.use_postgres:
            return 0.0
        total_size = 0
        for filename in [self.learned_file, self.users_file, self.stats_file, self.games_file]:
            if os.path.exists(filename):
                total_size += os.path.getsize(filename)
        return total_size / (1024 * 1024)

    async def init_db(self):
        """Инициализация PostgreSQL"""
        if not self.use_postgres:
            return

        database_url = os.getenv("DATABASE_URL")
        self.db_pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)

        await self.db_pool.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                name TEXT,
                username TEXT,
                first_seen TIMESTAMP,
                message_count INT,
                last_active TIMESTAMP
            )
        """)
        await self.db_pool.execute("""
            CREATE TABLE IF NOT EXISTS learned_responses (
                question TEXT PRIMARY KEY,
                answers JSONB
            )
        """)
        await self.db_pool.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                key TEXT PRIMARY KEY,
                value JSONB
            )
        """)
        await self.db_pool.execute("""
            CREATE TABLE IF NOT EXISTS active_games (
                game_id TEXT PRIMARY KEY,
                data JSONB
            )
        """)
        logger.info("PostgreSQL таблицы созданы.")

    async def load_all_data(self):
        """Загрузка данных из PostgreSQL или JSON"""
        if self.use_postgres:
            rows = await self.db_pool.fetch("SELECT * FROM users")
            for row in rows:
                self.user_data[str(row['user_id'])] = {
                    'name': row['name'],
                    'username': row['username'],
                    'first_seen': row['first_seen'].isoformat(),
                    'message_count': row['message_count'],
                    'last_active': row['last_active'].isoformat()
                }

            row = await self.db_pool.fetchrow("SELECT value FROM stats WHERE key = 'learned_responses'")
            if row:
                self.learned_responses = defaultdict(list, row['value'])

            row = await self.db_pool.fetchrow("SELECT value FROM stats WHERE key = 'main_stats'")
            if row:
                self.stats = row['value']
                if 'commands_used' in self.stats:
                    self.stats['commands_used'] = defaultdict(int, self.stats['commands_used'])
            else:
                self.stats = {
                    "total_messages": 0,
                    "unique_users": 0,
                    "games_played": 0,
                    "commands_used": defaultdict(int)
                }

            rows = await self.db_pool.fetch("SELECT * FROM active_games")
            for row in rows:
                self.active_games[row['game_id']] = row['data']
        else:
            self.learned_responses = self._load_json(self.learned_file, defaultdict(list))
            self.user_data = self._load_json(self.users_file, {})
            self.stats = self._load_json(self.stats_file, {
                "total_messages": 0,
                "unique_users": 0,
                "games_played": 0,
                "commands_used": defaultdict(int)
            })
            self.active_games = self._load_json(self.games_file, {})

        logger.info("Данные загружены.")

    async def save_all_data(self):
        """Сохранение данных в PostgreSQL или JSON"""
        if self.use_postgres:
            async with self.db_pool.acquire() as conn:
                async with conn.transaction():
                    for user_id_str, data in self.user_data.items():
                        await conn.execute(
                            """
                            INSERT INTO users (user_id, name, username, first_seen, message_count, last_active)
                            VALUES ($1, $2, $3, $4, $5, $6)
                            ON CONFLICT (user_id) DO UPDATE SET
                                name = EXCLUDED.name,
                                username = EXCLUDED.username,
                                message_count = EXCLUDED.message_count,
                                last_active = EXCLUDED.last_active
                            """,
                            int(user_id_str),
                            data['name'],
                            data['username'],
                            datetime.fromisoformat(data['first_seen']),
                            data['message_count'],
                            datetime.fromisoformat(data['last_active'])
                        )

                    await conn.execute(
                        "INSERT INTO stats (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = $2",
                        'learned_responses',
                        dict(self.learned_responses)
                    )

                    stats_copy = self.stats.copy()
                    if 'commands_used' in stats_copy:
                        stats_copy['commands_used'] = dict(stats_copy['commands_used'])
                    await conn.execute(
                        "INSERT INTO stats (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = $2",
                        'main_stats',
                        stats_copy
                    )

                    await conn.execute("DELETE FROM active_games")
                    for game_id, data in self.active_games.items():
                        await conn.execute(
                            "INSERT INTO active_games (game_id, data) VALUES ($1, $2)",
                            game_id, data
                        )
            logger.info("Данные сохранены в PostgreSQL.")
        else:
            self._save_json(self.learned_file, self.learned_responses)
            self._save_json(self.users_file, self.user_data)
            self._save_json(self.stats_file, self.stats)
            self._save_json(self.games_file, self.active_games)
            logger.info("Данные сохранены в JSON.")

    async def stop(self):
        logger.info("Остановка Изиды...")
        await self.save_all_data()
        if self.db_pool:
            await self.db_pool.close()
        await self.bot.session.close()

    async def run_webhook(self, webhook_url: str, listen: str = "0.0.0.0", port: int = 8000):
        logger.info(f"Установка webhook на {webhook_url}...")
        await self.bot.set_webhook(url=webhook_url, drop_pending_updates=True)

        await self.init_db()
        await self.load_all_data()

        from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
        import aiohttp.web

        app = aiohttp.web.Application()
        SimpleRequestHandler(dispatcher=self.dp, bot=self.bot).register(app, path=f"/{self.token}")
        setup_application(app, self.dp, bot=self.bot)

        runner = aiohttp.web.AppRunner(app)
        await runner.setup()
        site = aiohttp.web.TCPSite(runner, host=listen, port=port)
        await site.start()

        logger.info(f"Webhook сервер запущен на {listen}:{port}")
        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            await self.stop()