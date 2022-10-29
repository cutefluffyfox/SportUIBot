import logging
from os import getenv

import dotenv
from aiogram import Bot, Dispatcher, executor
from aiogram.types import Message, CallbackQuery
from aiogram.types.input_media import InputMediaPhoto
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils.exceptions import MessageNotModified
from aiogram.dispatcher import FSMContext
from requests.exceptions import ContentDecodingError, ConnectionError, RetryError

from modules import api, database, generators


# Configure logging
logging.basicConfig(
    format='%(asctime)s %(levelname)-8s %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S',
    # filename="logs.log"
)

# Initialize environment variables from .env file (if it exists)
dotenv.load_dotenv(dotenv.find_dotenv())
BOT_TOKEN = getenv('BOT_TOKEN')

# Check that critical variables are defined
if BOT_TOKEN is None:
    logging.critical('No BOT_TOKEN variable found in project environment')

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
SESSIONS = dict()


# States
class Registration(StatesGroup):
    email = State()
    password = State()


def update_session(user_id: int) -> bool:
    if SESSIONS.get(user_id) is None:
        SESSIONS[user_id] = database.create_session(user_id)
    return api.session_is_valid(SESSIONS[user_id]) if SESSIONS.get(user_id) is not None else False


@dp.message_handler(lambda msg: api.is_dead())
async def server_is_down(message: Message):
    await bot.send_message(
        message.from_user.id,
        'Sorry, sport site is not available at the moment. '
        'This bot cannot work without it. '
        'Come again later.'
    )


@dp.callback_query_handler(lambda c: not update_session(c.from_user.id))
async def session_problem(callback_query: CallbackQuery):
    chat_id = callback_query.message.chat.id
    user_id = callback_query.from_user.id
    if SESSIONS.get(user_id):
        await bot.delete_message(chat_id=chat_id, message_id=callback_query.message.message_id)
        await bot.send_message(
            chat_id=user_id,
            text="Your session expired, please login to continue. Enter your email:"
        )
    else:
        await bot.send_message(
            chat_id=user_id,
            text="Hello! I am sport in IU manager bot.\n"
                 "My goal is to help managing UI sport site. "
                 "I can help you get notifications about sport hours (for you not to forget), "
                 "check in you, collect statistics! "
                 "Let's get started. First I need your innopolis.university email:"
        )
    await Registration.email.set()
    await callback_query.answer('Updated')


@dp.message_handler(commands=['start', 'login'])
async def start(message: Message):
    await message.answer(
        "Hello! I am sport in IU manager bot.\n"
        "My goal is to help managing UI sport site. "
        "I can help you get notifications about sport hours (for you not to forget), check in you, collect statistics! "
        "Let's get started. First I need your innopolis.university email:"
    )
    await Registration.email.set()


@dp.message_handler(state=Registration.email)
async def process_email(message: Message, state: FSMContext):
    async with state.proxy() as data:
        data['email'] = message.text
    await Registration.next()
    await message.reply(
        text="And send password to your account "
             "(message will be automatically deleted, "
             "password [won't be stored](https://github.com/cutefluffyfox/SportUIBot))",
        disable_web_page_preview=True,
        parse_mode="Markdown"
    )


@dp.message_handler(state=Registration.password)
async def process_password(message: Message, state: FSMContext):
    user_id = message.from_user.id
    await bot.delete_message(message.chat.id, message.message_id)
    async with state.proxy() as data:
        try:
            session = api.login_user(email=data.get('email'), password=message.text)
            database.create_user(user_id=message.from_user.id, student_id=session.cookies['student_id'], session_id=session.cookies['sessionid'], csrftoken=session.cookies['csrftoken'])
            SESSIONS[user_id] = session
            generators.generate_today_image(user_id, session)
            await bot.send_message(user_id, 'You logged in successfully!')
            with open(f'images/{user_id}.png', 'rb') as file:
                await bot.send_photo(
                    chat_id=message.from_user.id,
                    caption=generators.generate_date_caption(generators.get_today()),
                    parse_mode='Markdown',
                    reply_markup=generators.generate_date_inline(generators.get_today()),
                    photo=file
                )
            await state.finish()
        except ContentDecodingError as ex:
            await Registration.first()
            await bot.send_message(
                message.from_user.id,
                'It seems like your data is invalid. Please check it once again.\n'
                'Send me your email one more time:'
            )
        except RetryError as ex:
            await Registration.first()
            await bot.send_message(message.from_user.id, 'Authentication server is down, please try again later.\nSend me your email one more time:')
        except ConnectionError as ex:
            await Registration.first()
            await bot.send_message(message.from_user.id, 'Sorry, sport server is down. Please try again later.\nSend me your email one more time:')
        except Exception as ex:
            await Registration.first()
            await bot.send_message(message.from_user.id, "Something went wrong with your authentication, please contact @cutefluffyfox or try again (probably won't help):\nSend your innopolis email:")


@dp.message_handler(lambda m: not update_session(m.from_user.id))
async def session_problem(message: Message):
    user_id = message.from_user.id
    if SESSIONS.get(user_id):
        await bot.send_message(
            chat_id=user_id,
            text="Your session expired, please login to continue. Enter your email:"
        )
    else:
        await bot.send_message(
            chat_id=user_id,
            text="Hello! I am sport in IU manager bot.\n"
                 "My goal is to help managing UI sport site. "
                 "I can help you get notifications about sport hours (for you not to forget), "
                 "check in you, collect statistics! "
                 "Let's get started. First I need your innopolis.university email:"
        )

    await Registration.email.set()


@dp.callback_query_handler(lambda c: c.data.startswith('my/'))
async def my_image(callback_query: CallbackQuery):
    date = callback_query.data.split('/')[1]
    user_id = callback_query.from_user.id
    contains = generators.draw_my_week(SESSIONS.get(user_id), user_id)
    try:
        with open(f'images/{user_id if contains else "sleep"}.png', 'rb') as file:
            await bot.edit_message_media(
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                media=InputMediaPhoto(file, caption=generators.generate_my_caption(SESSIONS.get(user_id)), parse_mode='Markdown'),
                reply_markup=generators.generate_my_inline(date)
            )
    except MessageNotModified as ex:
        pass
    await callback_query.answer('Your statistics')


@dp.callback_query_handler(lambda c: c.data == 'change')
async def change_day(callback_query: CallbackQuery):
    with open(f'images/change.png', 'rb') as file:
        await bot.edit_message_media(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            media=InputMediaPhoto(file, caption='Please select day of the week that you want to attend:'),
            reply_markup=generators.generate_inline_markup(
                *[{'text': f'{weekday} ({date})', 'callback_data': f'date/{date}'} for (date, weekday) in generators.get_week()]
            )
        )
    await callback_query.answer('Select day')


@dp.callback_query_handler(lambda c: c.data.startswith('date/'))
async def select_day(callback_query: CallbackQuery):
    date = callback_query.data.split('/')[1]
    user_id = callback_query.from_user.id
    contains = generators.generate_date_image(date, user_id, SESSIONS.get(user_id), rewrite=True)
    with open(f'images/{user_id if contains else "free"}.png', 'rb') as file:
        await bot.edit_message_media(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            media=InputMediaPhoto(file, caption=generators.generate_date_caption(date), parse_mode='Markdown'),
            reply_markup=generators.generate_date_inline(date)
        )
    await callback_query.answer('Select option')


@dp.callback_query_handler(lambda c: c.data.startswith('ckin/'))
async def select_type(callback_query: CallbackQuery):
    date = callback_query.data.split('/')[1]
    user_id = callback_query.from_user.id
    await bot.edit_message_caption(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        caption='Select sport type that you want to checkin:',
        reply_markup=generators.generate_date_courses_buttons(date, SESSIONS.get(user_id))
    )
    await callback_query.answer('Select course')


@dp.callback_query_handler(lambda c: c.data.startswith('gid/'))
async def select_time(callback_query: CallbackQuery):
    _, date, group_id = callback_query.data.split('/')
    group_id = int(group_id)
    user_id = callback_query.from_user.id
    await bot.edit_message_caption(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        caption=generators.generate_group_time_caption(group_id, SESSIONS.get(user_id)),
        reply_markup=generators.generate_date_group_time_buttons(date, group_id, SESSIONS.get(user_id)),
    )
    await callback_query.answer('Select time')


@dp.callback_query_handler(lambda c: c.data == 'auto')
async def auto_menu(callback_query: CallbackQuery):
    await callback_query.answer('This feature is under development stage. For more information contact @cutefluffyfox', show_alert=True)


@dp.callback_query_handler(lambda c: c.data.startswith('tid/'))
async def selected(callback_query: CallbackQuery):
    training_id = int(callback_query.data.split('/')[1])
    user_id = callback_query.from_user.id

    try:
        training = api.get_training_info(SESSIONS.get(user_id), training_id)
        if training['can_check_in'] and not training['checked_in']:
            api.checkin(SESSIONS.get(user_id), training_id)
        elif training['checked_in']:
            api.cancel_checkin(SESSIONS.get(user_id), training_id)
        else:
            await callback_query.answer('You cannot check in to this training')
            return

        training = api.get_training_info(SESSIONS.get(user_id), training_id)
        date = training['training']['start'].split('T')[0]
        group_id = training['training']['group']['id']
        contains = generators.generate_date_image(date, user_id, SESSIONS.get(user_id), rewrite=True)

        with open(f'images/{user_id if contains else "free"}.png', 'rb') as file:
            await bot.edit_message_media(
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                media=InputMediaPhoto(file, caption=generators.generate_group_time_caption(group_id, SESSIONS.get(user_id)), parse_mode='Markdown'),
                reply_markup=generators.generate_date_group_time_buttons(date, group_id, SESSIONS.get(user_id))
            )

        await callback_query.answer('Successfully changed status')
    except Exception as ex:
        await callback_query.answer('Some error occurred, please try again later', show_alert=True)


@dp.message_handler(commands=['logout'])
async def start(message: Message):
    user_id = message.from_user.id
    if SESSIONS.get(user_id):
        SESSIONS[user_id] = None
    database.remove_user(user_id)
    await message.reply("Your session information successfully deleted from the database")


@dp.message_handler()
async def unknown_message(message: Message):
    user_id = message.from_user.id
    contains = generators.generate_today_image(user_id, SESSIONS.get(user_id))
    with open(f'images/{user_id if contains else "sleep"}.png', 'rb') as file:
        await bot.send_photo(
            chat_id=message.from_user.id,
            caption=generators.generate_date_caption(generators.get_today()),
            parse_mode="Markdown",
            reply_markup=generators.generate_date_inline(generators.get_today()),
            photo=file
        )


if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
