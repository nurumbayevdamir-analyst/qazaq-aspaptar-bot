import os
import json
from pathlib import Path

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("На сервере не задан BOT_TOKEN.")

data_path = Path(__file__).resolve().parent / "muzykalyq_aspaptar.json"

with data_path.open(encoding="utf-8") as file:
    instruments = json.load(file)

import asyncio
import io
import random
import unicodedata

import requests
from PIL import Image, ImageOps

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery, KeyboardButton,
    ReplyKeyboardMarkup, BufferedInputFile,
    LinkPreviewOptions,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError


if not globals().get("BOT_TOKEN"):
    raise ValueError("Сначала загрузи BOT_TOKEN.")

if not globals().get("instruments"):
    raise ValueError("Сначала загрузи датасет.")


dp = Dispatcher()
by_id = {str(item["id"]): item for item in instruments}
categories = sorted({item["turi"] for item in instruments})
photo_cache = {}

menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🎵 Аспаптар тізімі")],
        [
            KeyboardButton(text="🔍 Іздеу"),
            KeyboardButton(text="📂 Санаттар"),
        ],
        [
            KeyboardButton(text="🎲 Кездейсоқ аспап"),
            KeyboardButton(text="ℹ️ Бот туралы"),
        ],
    ],
    resize_keyboard=True,
)


def instrument_buttons(items):
    builder = InlineKeyboardBuilder()
    for item in items:
        builder.button(
            text=item["atauy"],
            callback_data=f"instrument:{item['id']}",
        )
    builder.adjust(2)
    return builder.as_markup()


def normalize(text):
    text = unicodedata.normalize("NFC", text).casefold()
    text = text.translate(str.maketrans({
        "қ": "к", "ғ": "г", "ң": "н", "ә": "а",
        "ө": "о", "ұ": "у", "ү": "у", "і": "и",
    }))
    return "".join(c for c in text if c.isalnum())


def prepare_photo(url):
    if url in photo_cache:
        return photo_cache[url]

    response = requests.get(
        url,
        timeout=(10, 40),
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()

    with Image.open(io.BytesIO(response.content)) as original:
        image = ImageOps.exif_transpose(original).convert("RGBA")
        image.thumbnail((1280, 1280))

        background = Image.new("RGB", image.size, "white")
        background.paste(image, mask=image.getchannel("A"))

        buffer = io.BytesIO()
        background.save(buffer, "JPEG", quality=85, optimize=True)

    photo_cache[url] = buffer.getvalue()
    return photo_cache[url]


async def send_instrument(message, item):
    strings = item.get("isek_sany")
    variants = item.get("isek_sany_nuskalary", [])
    materials = item.get("materialy", [])

    if strings is not None:
        strings_text = str(strings)
    elif item["turi"].startswith("ішекті"):
        strings_text = "Дерек жоқ"
    else:
        strings_text = "Ішексіз аспап"

    text = (
        f"🎵 {item['atauy']}\n\n"
        f"📂 Түрі: {item['turi']}\n"
        f"🧵 Негізгі ішек саны: {strings_text}\n"
    )

    if variants:
        text += (
            "🔢 Нұсқалары: "
            + ", ".join(map(str, variants)) + "\n"
        )

    text += (
        "🪵 Материалы: "
        + (", ".join(materials) if materials else "Дерек жоқ")
        + f"\n\n📖 {item['sipattamasy']}"
    )

    if "schema_turi_shekteui" in item.get("sapa_belgileri", []):
        text += (
            "\n\nℹ️ Шаңқобыз — тілшелі аспап. "
            "Датасеттегі санат шартты түрде берілген."
        )

    # Сначала описание, чтобы не ждать загрузки фотографии
    await message.answer(text)

    photos = item.get("suretter", [])
    url = photos[0].get("url") if photos else None

    if url:
        try:
            image_bytes = await asyncio.to_thread(
                prepare_photo, url
            )
            await message.answer_photo(
                photo=BufferedInputFile(
                    image_bytes,
                    filename=f"instrument_{item['id']}.jpg",
                ),
                caption=(
                    f"🎵 {item['atauy']}\n"
                    "Фото: Ықылас музейінің каталогы"
                ),
            )
        except (
            requests.RequestException, OSError, ValueError,
            TelegramBadRequest, TelegramNetworkError,
        ) as error:
            print(
                f"Фото: {item['atauy']} — "
                f"{type(error).__name__}"
            )
            await message.answer(
                "🖼 Фото уақытша қолжетімсіз.\n" + url
            )

    sources = item.get("derekkozder", [])
    if sources:
        await message.answer(
            "🔗 Дереккөздер:\n" + "\n".join(sources),
            link_preview_options=LinkPreviewOptions(
                is_disabled=True
            ),
        )


@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        "Сәлем! 👋\n\n"
        "Қазақтың 25 музыкалық аспабымен танысайық!\n"
        "Аспапты мәзірден таңдаңыз немесе атауын жазыңыз.",
        reply_markup=menu,
    )


# Все текстовые действия обрабатываются в одном месте
@dp.message(F.text)
async def text_handler(message: Message):
    text = message.text.strip()

    if text == "🎵 Аспаптар тізімі":
        await message.answer(
            "Аспапты таңдаңыз:",
            reply_markup=instrument_buttons(instruments),
        )
        return

    if text == "🔍 Іздеу":
        await message.answer(
            "Аспаптың атауын жазыңыз.\n"
            "Мысалы: кобыз, домбыра немесе жетіген."
        )
        return

    if text == "📂 Санаттар":
        builder = InlineKeyboardBuilder()

        for index, category in enumerate(categories):
            count = sum(
                item["turi"] == category for item in instruments
            )
            builder.button(
                text=f"{category} ({count})",
                callback_data=f"category:{index}",
            )

        builder.adjust(1)
        await message.answer(
            "Санатты таңдаңыз:",
            reply_markup=builder.as_markup(),
        )
        return

    if text == "🎲 Кездейсоқ аспап":
        await send_instrument(
            message, random.choice(instruments)
        )
        return

    if text == "ℹ️ Бот туралы":
        await message.answer(
            "🎵 Музыкалық аспаптар\n\n"
            "25 аспап: фотосуреттер, сипаттамалар, "
            "іздеу және санаттар.\n\n"
            "Дереккөздер: Ықылас музейі, "
            "Bilim-All, Sputnik Қазақстан."
        )
        return

    if text.startswith("/"):
        await message.answer(
            "Мәзірді ашу үшін /start жіберіңіз.",
            reply_markup=menu,
        )
        return

    query = normalize(text)

    if not query:
        await message.answer("Аспаптың атауын жазыңыз.")
        return

    aliases = {
        normalize("Қылқобыз"): normalize("Қобыз"),
        normalize("Уілдек"): normalize("Үскірік"),
    }
    query = aliases.get(query, query)

    matches = [
        item for item in instruments
        if query in normalize(item["atauy"])
    ]

    if not matches:
        await message.answer(
            "Аспап табылмады. Басқа атауды жазыңыз."
        )
    elif len(matches) == 1:
        await send_instrument(message, matches[0])
    else:
        await message.answer(
            f"Табылған аспаптар: {len(matches)}",
            reply_markup=instrument_buttons(matches),
        )


@dp.callback_query(F.data.startswith("instrument:"))
async def instrument_handler(callback: CallbackQuery):
    await callback.answer()

    item = by_id.get(callback.data.split(":", 1)[1])

    if item and isinstance(callback.message, Message):
        await send_instrument(callback.message, item)


@dp.callback_query(F.data.startswith("category:"))
async def category_handler(callback: CallbackQuery):
    await callback.answer()

    try:
        index = int(callback.data.split(":", 1)[1])
        if not 0 <= index < len(categories):
            return
        category = categories[index]
    except (ValueError, IndexError):
        return

    items = [
        item for item in instruments
        if item["turi"] == category
    ]

    if isinstance(callback.message, Message):
        await callback.message.answer(
            f"📂 {category}",
            reply_markup=instrument_buttons(items),
        )


@dp.message()
async def other_handler(message: Message):
    await message.answer(
        "Аспаптың атауын мәтінмен жазыңыз "
        "немесе мәзірден таңдаңыз.",
        reply_markup=menu,
    )


async def run_bot():
    async with Bot(token=BOT_TOKEN.strip()) as bot:
        info = await bot.get_me()
        print(f"✅ Бот: @{info.username}")
        print("✅ Каталог, фотографии, поиск и категории готовы.")
        print("В Telegram отправь /start.")

        await dp.start_polling(
            bot,
            handle_signals=False,
            close_bot_session=False,
        )


if __name__ == "__main__":
    asyncio.run(run_bot())