import datetime
import logging
import atexit
from os import getenv
import calendar
import random

import dotenv
from aiogram import Bot, Dispatcher, executor
from aiogram.types import Message, CallbackQuery
from aiogram.types.input_media import InputMediaPhoto
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils.exceptions import MessageNotModified
from aiogram.dispatcher import FSMContext
from requests.exceptions import ContentDecodingError, ConnectionError, RetryError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from modules import api, database, generators

# Configure logging
logging.basicConfig(
    format='%(asctime)s %(levelname)-8s %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Initialize environment variables from .env file (if it exists)
dotenv.load_dotenv(dotenv.find_dotenv())
BOT_TOKEN = getenv('BOT_TOKEN')
ADMIN_ID = getenv('ADMIN_ID')

# Check that critical variables are defined
if BOT_TOKEN is None:
    logging.critical('No BOT_TOKEN variable found in project environment')
if ADMIN_ID is None:
    logging.critical('No ADMIN_ID variable found in project environment')
else:
    ADMIN_ID = int(ADMIN_ID)

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
SESSIONS = dict()
LOGIN_REQUEST = dict()


# States
class ModeSelection(StatesGroup):
    idling = State()


class RegistrationOffline(StatesGroup):
    user_id = State()


class RegistrationFull(StatesGroup):
    email = State()
    password = State()


class BroadcastInfo(StatesGroup):
    message = State()
    confirmation = State()


async def send_users(users: list, text: str, reply_markup: dict = None, segregate_offline: dict = None):
    logging.info('Auto-broadcast mode activated')
    for user_id in users:
        try:
            await bot.send_message(chat_id=user_id, text=text, reply_markup=generators.generate_inline_markup(segregate_offline if segregate_offline else reply_markup))
        except Exception:
            pass


async def handle_notifications():
    if not update_session(ADMIN_ID):
        logging.warning('Admin session died')
        SESSIONS[ADMIN_ID] = api.login_user(getenv('ADMIN_EMAIL'), getenv('ADMIN_PSW'))

    notifications = database.get_notifications()
    for training_id in notifications:
        training_info = api.get_training_info(session=SESSIONS.get(ADMIN_ID), training_id=training_id)
        end_time = datetime.datetime.fromisoformat(training_info['training']['end'])
        capacity = training_info['training']['group']['capacity']
        load = capacity - training_info['training']['load']

        if end_time.timestamp() <= datetime.datetime.now().timestamp():
            notification_users = database.get_notification_users(training_id)
            logging.info(f'Notification expired for {training_id} and {len(notification_users)} users')
            training_name = training_info['training']['group']['name']
            training_time = end_time.strftime("%H:%M")
            training_day = end_time.strftime('%d/%m/%Y')
            weekday = calendar.day_name[end_time.weekday()]
            text = f'Sorry, but no free spaces appeared for a {training_name} at {training_time} on {weekday} ' \
                   f'({training_day}).\n' \
                   f'Not to got into the same situation again see autocheckin feature in `My sports`'
            await send_users(notification_users, text)
            database.remove_notification(training_id)

        elif load > 0:
            notification_users = database.get_notification_users(training_id)
            logging.info(f'Notification succeed for {training_id} and users {len(notification_users)}')
            training_name = training_info['training']['group']['name']
            training_time = end_time.strftime("%H:%M")
            training_day = end_time.strftime('%d/%m/%Y')
            weekday = calendar.day_name[end_time.weekday()]
            text = f"There is one available place for a {training_name} at {training_time} on {weekday} ({training_day}) ! Check-in ASAP!\nThis message has been sent to {len(notification_users) - 1} more people"
            await send_users(notification_users, text, {'text': '‼️Check-in ‼', 'callback_data': f'rawckin/{training_id}'}, segregate_offline={'text': 'Got it', 'callback_data': 'del'})
            database.remove_notification(training_id)


async def handle_check_in():
    if not update_session(ADMIN_ID):
        logging.warning('Admin session died')
        SESSIONS[ADMIN_ID] = api.login_user(getenv('ADMIN_EMAIL'), getenv('ADMIN_PSW'))

    auto_checkins = database.get_auto_checkins()
    if auto_checkins is None:
        return
    for user_id in auto_checkins:

        if not update_session(user_id):
            if not LOGIN_REQUEST.get(user_id, False):
                LOGIN_REQUEST[user_id] = True

                await bot.send_message(
                    chat_id=user_id,
                    text='Your session died, please login one more time to keep your auto-checkin running',
                    reply_markup=generators.generate_delete_inline('Login!'),
                )
            continue

        for training_key, sport_list in auto_checkins[user_id].items():
            for training_id in sport_list:
                training_info = api.get_training_info(SESSIONS.get(user_id), training_id)

                if training_info.get('detail') is not None:
                    group_id, weekday, time = training_key.split('|')
                    group_info = api.get_group_info(SESSIONS.get(ADMIN_ID), group_id)

                    user_message = \
                        f'Hello! Some changes to schedule was made and we found out that your sport ' \
                        f'{group_info["group_name"]} on {calendar.day_name[int(weekday)]} at {time} is no longer ' \
                        f'available for check-in. Please check new schedule for the day to see changes. Sorry for ' \
                        f'inconvenience.'

                    with open(f'images/something_happened.png', 'rb') as file:
                        await bot.send_photo(
                            chat_id=user_id,
                            caption=user_message,
                            parse_mode='Markdown',
                            reply_markup=generators.generate_investigate_inline(),
                            photo=file
                        )

                    database.remove_auto_checkin(user_id, training_key)
                    generators.generate_auto_checkin_list_caption()
                    break

                if datetime.datetime.fromisoformat(training_info['training']['end'].split('+')[0]) < datetime.datetime.now():
                    database.remove_given_auto_checkin(user_id, training_key, training_id)
                    continue

                if training_info['checked_in']:
                    database.remove_given_auto_checkin(user_id, training_key, training_id)
                    continue

                training_start = datetime.datetime.fromisoformat(training_info['training']['start'].split('+')[0])

                if not training_info['can_check_in'] or datetime.datetime.now() + datetime.timedelta(days=7) <= training_start:
                    break

                load = training_info['training']['group']['capacity'] - training_info['training']['load']
                if load > 0 and training_info['can_check_in'] and not training_info['checked_in']:
                    api.checkin(SESSIONS.get(user_id), training_id)
                    database.remove_given_auto_checkin(user_id, training_key, training_id)

                    group_id, weekday, time = training_key.split('|')
                    bot_info = await bot.get_me()

                    user_message = \
                        f'I checked you in to next {training_info["training"]["group"]["name"]} on ' \
                        f'{calendar.day_name[int(weekday)]} at {time} ({training_start.strftime("%d/%m/%Y")}).\n' \
                        f'Thanks for using @{bot_info["username"]}!'

                    await bot.send_message(
                        chat_id=user_id,
                        text=user_message,
                        parse_mode='Markdown',
                        reply_markup=generators.generate_delete_inline(),
                    )
                break


scheduler = AsyncIOScheduler()
scheduler.add_job(func=handle_notifications, trigger="interval", seconds=30)
scheduler.add_job(func=handle_check_in, trigger="interval", seconds=30)
scheduler.start()
logging.getLogger('apscheduler.executors.default').setLevel(logging.WARNING)

# Shut down the scheduler when exiting the app
atexit.register(lambda: scheduler.shutdown())


def update_session(user_id: int) -> bool:
    if SESSIONS.get(user_id) is None:
        SESSIONS[user_id] = database.create_session(user_id)

    if SESSIONS.get(user_id) is None:
        return False
    if SESSIONS.get(user_id).cookies.get('sessionid') is None:  # offline users are valid users with valid session
        return True
    return api.session_is_valid(SESSIONS[user_id])


def is_offline(user_id: int) -> bool:
    update_session(user_id)
    return (SESSIONS.get(user_id) is not None) and (SESSIONS.get(user_id).cookies.get('sessionid') is None)


@dp.message_handler(lambda msg: api.is_dead())
async def server_is_down(message: Message):
    await bot.send_message(
        message.from_user.id,
        'Sorry, sport site is not available at the moment. '
        'This bot cannot work without it. '
        'Come again later.'
    )


@dp.callback_query_handler(lambda c: c.data.startswith('start/'))
async def start_registration(callback_query: CallbackQuery):
    mode = callback_query.data.split('/')[1]
    await callback_query.answer('Nice choice!')

    if mode == 'offline':
        if not callback_query.message.photo:
            await bot.edit_message_text(
                text='To access offline mode I only need one thing - your id on the sport website\n\n'
                     'You can find it pretty easily:\n'
                     '1. Go to [your profile](https://sport.innopolis.university/profile/) \n'
                     '2. Open \`Console\` (F12 of just right click)\n'
                     '3. Type \`student\_id\` and press Enter\n'
                     '4. Copy 3-4 digit number (e.x. 1082)\n\n'
                     'Please type your student\_id:',
                message_id=callback_query.message.message_id,
                chat_id=callback_query.message.chat.id,
                parse_mode='Markdown'
            )
        else:
            await bot.edit_message_caption(
                caption='To access offline mode I only need one thing - your id on the sport website\n\n'
                         'You can find it pretty easily:\n'
                         '1. Go to [your profile](https://sport.innopolis.university/profile/) \n'
                         '2. Open \`Console\` (F12 of just right click)\n'
                         '3. Type \`student\_id\` and press Enter\n'
                         '4. Copy 3-4 digit number (e.x. 1082)\n\n'
                         'Please type your student\_id:',
                message_id=callback_query.message.message_id,
                chat_id=callback_query.message.chat.id,
                parse_mode='Markdown'
            )
        await RegistrationOffline.user_id.set()
    else:  # mode == 'full'
        if not callback_query.message.photo:
            await bot.edit_message_text(
                message_id=callback_query.message.message_id,
                chat_id=callback_query.message.chat.id,
                text='To access full-experience mode you need to register. First I need your innopolis.university email:'
            )
        else:
            await bot.edit_message_caption(
                message_id=callback_query.message.message_id,
                chat_id=callback_query.message.chat.id,
                caption='To access full-experience mode you need to register. First I need your innopolis.university email:'
            )
        await RegistrationFull.email.set()


@dp.callback_query_handler(lambda c: not update_session(c.from_user.id))
async def session_problem_button(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if SESSIONS.get(user_id) and not callback_query.message.photo:
        await bot.send_message(
            chat_id=user_id,
            text="Seems like your session expired, please login to continue or switch to offline mode. How would you like to continue?",
            reply_markup=generators.generate_mode_selection_inline()
        )
    elif SESSIONS.get(user_id) and callback_query.message.photo:
        with open(f'images/dead_session.png', 'rb') as file:
            await bot.edit_message_media(
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                media=InputMediaPhoto(file, caption="Seems like your session expired, please login to continue or switch to offline mode. How would you like to continue?"),
                reply_markup=generators.generate_mode_selection_inline()
            )
    else:
        await bot.send_message(
            chat_id=user_id,
            text="Hello! I am sport in IU manager bot.\n\n"
                 "My goal is to _help managing IU_ sport site. "
                 "I can help you get notifications about sport hours (for you not to forget), "
                 "set up autocheckin so you would never miss your trainings, "
                 "collect statistics and much-much more!\n"
                 "Let's get started.\n"
                 "\n"
                 "I support two modes:\n"
                 "> _Offline_ \[no registration required] - you can check schedule, add notifications and see your statistics\n"
                 "> _Full-experience_ \[registration required] - everything as offline + check-in + autocheck-in\n\n"
                 "How would you like to use me?",
            reply_markup=generators.generate_mode_selection_inline()
        )

    await callback_query.answer('Updated')


@dp.message_handler(lambda m: not update_session(m.from_user.id))
async def session_problem_message(message: Message):
    user_id = message.from_user.id
    LOGIN_REQUEST[user_id] = False
    if SESSIONS.get(user_id):
        await bot.send_message(
            chat_id=user_id,
            text="Seems like your session has expired, please login to continue or switch to offline mode. How would you like to login?",
            reply_markup=generators.generate_mode_selection_inline()
        )
    else:
        await bot.send_message(
            chat_id=message.from_user.id,
            text="Hello! I am sport in IU manager bot.\n\n"
                 "My goal is to _help managing IU_ sport site. "
                 "I can help you get notifications about sport hours (for you not to forget), "
                 "set up autocheckin so you would never miss your trainings, "
                 "collect statistics and much-much more!\n"
                 "Let's get started.\n"
                 "\n"
                 "I support two modes:\n"
                 "> _Offline_ \[no registration required] - you can check schedule, add notifications and see your statistics\n"
                 "> _Full-experience_ \[registration required] - everything as offline + check-in + autocheck-in\n\n"
                 "How would you like to use me?",
            reply_markup=generators.generate_mode_selection_inline(),
            parse_mode='Markdown'
        )


@dp.message_handler(commands=['start', 'login'])
async def start(message: Message):
    await bot.send_message(
        chat_id=message.from_user.id,
        text="Hello! I am sport in IU manager bot.\n\n"
             "My goal is to _help managing IU_ sport site. "
             "I can help you get notifications about sport hours (for you not to forget), "
             "set up autocheckin so you would never miss your trainings, "
             "collect statistics and much-much more!\n"
             "Let's get started.\n"
             "\n"
             "I support two modes:\n"
             "> _Offline_ \[no registration required] - you can check schedule, add notifications and see your statistics\n"
             "> _Full-experience_ \[registration required] - everything as offline + check-in + autocheck-in\n\n"
             "How would you like to use me?",
        reply_markup=generators.generate_mode_selection_inline(),
        parse_mode='Markdown'
        )


@dp.message_handler(state=RegistrationOffline.user_id)
async def process_sport_user_id(message: Message, state: FSMContext):
    user_id = message.from_user.id
    student_id = message.text.replace('\'"', '')
    print(user_id, student_id)
    print(api.student_id_is_valid(SESSIONS.get(ADMIN_ID), student_id))

    if not api.student_id_is_valid(SESSIONS.get(ADMIN_ID), student_id):
        await bot.send_message(
            chat_id=user_id,
            text="Seems like this student_id is invalid, please check and try again. How would you like to login?",
            reply_markup=generators.generate_mode_selection_inline()
        )
        await state.finish()
        return

    database.create_user(user_id=user_id, student_id=student_id)
    update_session(user_id)

    generators.generate_today_image(user_id, SESSIONS.get(ADMIN_ID), ignore_checked_in=True)

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


@dp.message_handler(state=RegistrationFull.email)
async def process_email(message: Message, state: FSMContext):
    async with state.proxy() as data:
        data['email'] = message.text
    await RegistrationFull.next()
    await message.reply(
        text="And send password to your account "
             "(message will be automatically deleted, "
             "password [won't be stored](https://github.com/cutefluffyfox/SportUIBot))",
        disable_web_page_preview=True,
        parse_mode="Markdown"
    )


@dp.message_handler(state=RegistrationFull.password)
async def process_password(message: Message, state: FSMContext):
    user_id = message.from_user.id
    await bot.delete_message(message.chat.id, message.message_id)
    async with state.proxy() as data:
        try:
            session = api.login_user(email=data.get('email'), password=message.text)
            database.create_user(
                user_id=message.from_user.id,
                student_id=session.cookies['student_id'],
                session_id=session.cookies['sessionid'],
                csrftoken=session.cookies['csrftoken']
            )
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
            await bot.send_message(
                message.from_user.id,
                'It seems like your data is invalid. Please check it and try again. How would you like to login?',
                reply_markup=generators.generate_mode_selection_inline()
            )
            await state.finish()
        except RetryError as ex:
            await RegistrationFull.first()
            await bot.send_message(
                message.from_user.id,
                'Authentication server is down, please try again later.\nSend me your email one more time:'
            )
        except ConnectionError as ex:
            await RegistrationFull.first()
            await bot.send_message(
                message.from_user.id,
                'Sorry, sport server is down. Please try again later.\nSend me your email one more time:')
        except Exception as ex:
            await RegistrationFull.first()
            await bot.send_message(
                message.from_user.id,
                "Something went wrong with your authentication, please contact @cutefluffyfox or "
                "try again (probably won't help):\nSend your innopolis email:")


@dp.callback_query_handler(lambda c: c.data.startswith('my/'))
async def my_image(callback_query: CallbackQuery):
    date = callback_query.data.split('/')[1]
    user_id = callback_query.from_user.id

    render = 'please_register'
    if not is_offline(user_id):
        render = generators.draw_my_week(SESSIONS.get(user_id), user_id)
        render = user_id if render else 'sleep'  # if none sport selected

    try:
        with open(f'images/{render}.png', 'rb') as file:
            await bot.edit_message_media(
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                media=InputMediaPhoto(
                    file,
                    caption=generators.generate_my_caption(SESSIONS.get(user_id)),
                    parse_mode='Markdown'),
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
                *[{'text': f'{weekday} ({date})', 'callback_data': f'date/{date}'} for (date, weekday) in
                  generators.get_week()]
            )
        )
    await callback_query.answer('Select day')


@dp.callback_query_handler(lambda c: c.data.startswith('date/'))
async def select_day(callback_query: CallbackQuery):
    date = callback_query.data.split('/')[1]
    user_id = callback_query.from_user.id

    if is_offline(user_id):
        contains = generators.generate_date_image(date, user_id, SESSIONS.get(ADMIN_ID), rewrite=True, ignore_checked_in=True)
    else:
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
    await bot.edit_message_caption(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        caption='Select sport type that you want to checkin:',
        reply_markup=generators.generate_date_courses_buttons(date, SESSIONS.get(ADMIN_ID))
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
        caption=generators.generate_group_time_caption(group_id, SESSIONS.get(ADMIN_ID)),
        reply_markup=generators.generate_date_group_time_buttons(date, group_id, SESSIONS.get(ADMIN_ID if is_offline(user_id) else user_id), user_id, ignore_checked_in=is_offline(user_id)),
    )
    await callback_query.answer('Select time')


@dp.callback_query_handler(lambda c: c.data.startswith('auto'))
async def auto_menu(callback_query: CallbackQuery):
    date = callback_query.data.split('/')[1]
    user_id = callback_query.from_user.id

    if is_offline(user_id):
        await callback_query.answer('Please switch to a `full-experience mode` in order to set autocheckin', show_alert=True)
        return

    await bot.edit_message_caption(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        caption=generators.generate_auto_checkin_list_caption(),
        reply_markup=generators.generate_auto_checkin_list_markup(SESSIONS.get(user_id), date, user_id)
    )
    await callback_query.answer('Select training')


@dp.callback_query_handler(lambda c: c.data == 'why')
async def why_did_you_click_it(callback_query: CallbackQuery):
    why_messages = [
        'Why? Just why?'
        'Why you clicked it?',
        'Why would you do that?',
        'How bored are you that you would actually click that random button?',
        'Are you insane?',
        'I am truly shocked that you are here reading this.',
        "If you are serious, message me at @cutefluffyfox, and I'll see what I can do to help you.",
        'You must be crazy.'
    ]
    await callback_query.answer(random.choice(why_messages), show_alert=True)


@dp.callback_query_handler(lambda c: c.data.startswith('aid/'))
async def set_auto_checkin(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    _, date, training_key = callback_query.data.split('/')

    auto_checked_in = database.check_auto_checkin(user_id, training_key)
    if auto_checked_in:
        database.remove_auto_checkin(user_id, training_key)
    else:
        group_id = training_key.split('/')[0]
        if group_id in ['436']:  # Some Teachers have request to disable this feature. Please respect them.
            await callback_query.answer(
                text='Teacher of this course requested to disable this feature. '
                     'Please respect them and use notification system',
                show_alert=True)
            return
        training_ids = generators.get_training_ids_to_auto_checkin(SESSIONS.get(user_id), training_key.replace('|', '/'))
        database.add_auto_checkin(user_id, training_key, training_ids)

    await bot.edit_message_reply_markup(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        reply_markup=generators.generate_auto_checkin_list_markup(SESSIONS.get(user_id), date, user_id)
    )

    await callback_query.answer(
        'Auto-checkin removed successfully' if auto_checked_in else 'Auto-checkin set successfully')


@dp.callback_query_handler(lambda c: c.data.startswith('unckin/'))
async def selected(callback_query: CallbackQuery):
    date = callback_query.data.split('/')[1]
    user_id = callback_query.from_user.id

    if is_offline(user_id):
        await callback_query.answer('Please switch to a `full-experience mode` in order to uncheckin', show_alert=True)
        return

    await bot.edit_message_caption(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        caption=generators.generate_fast_un_checkin_caption(),
        reply_markup=generators.generate_fast_un_checkin_markup(SESSIONS.get(user_id), date)
    )


@dp.callback_query_handler(lambda c: c.data.startswith('tid/') or c.data.startswith('ntid/'))
async def selected(callback_query: CallbackQuery):
    training_id = int(callback_query.data.split('/')[1])
    user_id = callback_query.from_user.id
    callback_type = callback_query.data.split('/')[0]

    if is_offline(user_id) and callback_type == 'tid':
        await callback_query.answer('Please switch to a `full-experience mode` in order to check in', show_alert=True)
        return

    try:
        training = api.get_training_info(SESSIONS.get(user_id if not is_offline(user_id) else ADMIN_ID), training_id)
        start_datetime = datetime.datetime.fromisoformat(training['training']['start'].split('+')[0])
        if callback_type == 'tid':
            if training['can_check_in'] and not training['checked_in']:
                api.checkin(SESSIONS.get(user_id), training_id)
            elif training['checked_in']:
                api.cancel_checkin(SESSIONS.get(user_id), training_id)
            elif datetime.datetime.now() + datetime.timedelta(days=7) < start_datetime:
                await callback_query.answer(
                    'This training is not available for checkin now', show_alert=True)
                return
            else:
                await callback_query.answer(
                    'Free seats for this workout are over, but you can turn on notifications to get '
                    'information when at least one seat appears', show_alert=True)
                return
        else:
            notified_users = database.get_notification_users(training_id)
            if user_id in notified_users:
                database.remove_user_notification(training_id, user_id)
            else:
                database.add_user_notification(training_id, user_id)

        training = api.get_training_info(SESSIONS.get(ADMIN_ID), training_id)
        date = training['training']['start'].split('T')[0]
        group_id = training['training']['group']['id']

        if is_offline(user_id):
            contains = generators.generate_date_image(date, user_id, SESSIONS.get(ADMIN_ID), rewrite=True, ignore_checked_in=True)
        else:
            contains = generators.generate_date_image(date, user_id, SESSIONS.get(user_id), rewrite=True)

        with open(f'images/{user_id if contains else "free"}.png', 'rb') as file:
            await bot.edit_message_media(
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                media=InputMediaPhoto(
                    file,
                    caption=generators.generate_group_time_caption(group_id, SESSIONS.get(ADMIN_ID)),
                    parse_mode='Markdown'),
                reply_markup=generators.generate_date_group_time_buttons(date, group_id, SESSIONS.get(ADMIN_ID if is_offline(user_id) else user_id), user_id, ignore_checked_in=is_offline(user_id)),

            )

        await callback_query.answer('Notification status changed' if callback_type == 'ntid' else 'Information updated')
    except Exception as ex:
        await callback_query.answer('Some error occurred, please try again later', show_alert=True)


@dp.callback_query_handler(lambda c: c.data.startswith('rawckin/') or c.data.startswith('rawnid/') or c.data.startswith('fckin/'))
async def raw_checkin(callback_query: CallbackQuery):
    training_id = int(callback_query.data.split('/')[1])
    user_id = callback_query.from_user.id
    callback_type = callback_query.data.split('/')[0]

    training_info = api.get_training_info(SESSIONS.get(user_id), training_id)
    if callback_type == 'rawckin' or callback_type == 'fckin':
        if training_info['can_check_in'] and not training_info['checked_in']:
            api.checkin(SESSIONS.get(user_id), training_id)

            if callback_type == 'rawckin':  # message with no image
                await bot.delete_message(
                    chat_id=user_id,
                    message_id=callback_query.message.message_id
                )
            else:
                contains = generators.draw_my_week(SESSIONS.get(user_id), user_id)  # offline guys should never reach
                with open(f'images/{user_id if contains else "sleep"}.png', 'rb') as file:
                    await bot.edit_message_media(
                        chat_id=callback_query.message.chat.id,
                        message_id=callback_query.message.message_id,
                        media=InputMediaPhoto(
                            file,
                            caption=generators.generate_fast_un_checkin_caption(),
                            parse_mode='Markdown'),
                        reply_markup=generators.generate_fast_un_checkin_markup(SESSIONS.get(user_id),
                                                                                previous_markup=callback_query.message.reply_markup)
                    )

        elif training_info['checked_in']:
            api.cancel_checkin(SESSIONS.get(user_id), training_id)

            if callback_query.message.photo is not None:
                contains = generators.draw_my_week(SESSIONS.get(user_id), user_id)
                with open(f'images/{user_id if contains else "sleep"}.png', 'rb') as file:
                    await bot.edit_message_media(
                        chat_id=callback_query.message.chat.id,
                        message_id=callback_query.message.message_id,
                        media=InputMediaPhoto(
                            file,
                            caption=generators.generate_fast_un_checkin_caption(),
                            parse_mode='Markdown'),
                        reply_markup=generators.generate_fast_un_checkin_markup(SESSIONS.get(user_id),
                                                                                previous_markup=callback_query.message.reply_markup)
                    )

        else:
            await callback_query.answer(
                'Free seats for this workout are over, but you can turn on '
                'notifications to get information when at least one seat appears',
                show_alert=True
            )
            await bot.edit_message_reply_markup(
                chat_id=user_id,
                message_id=callback_query.message.message_id,
                reply_markup=generators.generate_inline_markup(
                    {'text': 'Notify me 🔔', 'callback_data': f'rawnid/{training_id}'})
            )
    else:
        database.add_user_notification(training_id, user_id)
        await bot.delete_message(
            chat_id=user_id,
            message_id=callback_query.message.message_id
        )
        await callback_query.answer('Success')


@dp.callback_query_handler(lambda c: c.data == 'del')
async def delete_message(callback_query: CallbackQuery):
    await callback_query.message.delete()
    await callback_query.answer('Nice!')


@dp.callback_query_handler(lambda c: c.data.startswith('logout/'))
async def logout_approve(callback_query: CallbackQuery):
    date = callback_query.data.split('/')[1]
    user_id = callback_query.from_user.id

    await bot.edit_message_caption(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        caption='You sure you want to logout?',
        reply_markup=generators.generate_logout_inline(date)
    )


@dp.callback_query_handler(lambda c: c.data == 'logoutnow')
async def logout_now(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if SESSIONS.get(user_id):
        SESSIONS[user_id] = None
    database.remove_user(user_id)
    await bot.send_message(
        chat_id=callback_query.from_user.id,
        text="Your session information successfully deleted from the database. Message /start if you want to register."
    )


@dp.message_handler(commands=['logout'])
async def logout(message: Message):
    user_id = message.from_user.id
    if SESSIONS.get(user_id):
        SESSIONS[user_id] = None
    database.remove_user(user_id)
    await message.reply("Your session information successfully deleted from the database. Message /start if you want to register.")


@dp.message_handler(commands=['repo'])
async def repo(message: Message):
    await message.reply(
        "Thank you for being interested in project\! Here is "
        "[open source code](https://github.com/cutefluffyfox/SportUIBot)\. "
        "Good luck exploring\!",
        parse_mode='MarkdownV2')


@dp.message_handler(commands=['support'])
async def support(message: Message):
    await message.reply(
        f"Thanks for being supportive of this project!\n\nIf you want to help, you can contact me at telegram "
        f"@cutefluffyfox to help with new ideas and bugs. If you want, you can even "
        f"[buy me]({getenv('CROWDFUNDING')}) a cup of coffe =W=. Thanks for all the support! <3\n\n"
        f"P.S. To continue using bot, send /now",
        parse_mode='Markdown'
    )


@dp.message_handler(lambda msg: msg.from_user.id == ADMIN_ID, commands=['kill'])
async def kill_application(message: Message):
    logging.critical('Attempt to kill bot')
    if message.from_user.id == ADMIN_ID:  # useless if, but extra safety is nice
        await bot.send_message(chat_id=message.chat.id, text='Killing initiated')
        dp.stop_polling()
        exit(12345678)


@dp.message_handler(lambda msg: msg.from_user.id == ADMIN_ID, commands=['reload_semester'])
async def reload_semester(message: Message):
    logging.critical('Reload semester_trainings.json file')
    if message.from_user.id == ADMIN_ID:  # useless if, but extra safety is nice
        generators.parse_and_save_whole_semester(SESSIONS.get(ADMIN_ID))


@dp.message_handler(lambda msg: msg.from_user.id == ADMIN_ID, commands=['broadcast'])
async def broadcast_message(message: Message):
    await bot.send_message(chat_id=message.chat.id, text='Please send message that you want to broadcast to users')
    await BroadcastInfo.message.set()


@dp.message_handler(commands=['help'])
async def print_help(message: Message):
    if message.from_user.id == ADMIN_ID:  # special for admin only
        await message.reply(
            'You are admin, how you have forgotten your commands? Ok, let me explain:\n'
            '/reload_semester - you will reload huge file that contains info about all trainings for current semester (used in auto-checkin)\n'
            '/broadcast - you will open menu to send message to all users (statistic will be provided). '
            'MardownV2 is implemented, so you can add *balled*, _italic_ and |spoiler| messages!\n'
            '/kill - kill bot even if you are not connected to university wifi\n'
        )
    else:
        await message.reply(
            'Hi! I am surprised you here. This is inline-based bot so commands are pretty useless, however there are some:\n'
            '/login - login to your account\n'
            '/logout - remove all the data about you from the database\n'
            '/repo - get link to github repository\n'
            '/support - support creator of the bot\n'
            '/now - get schedule for today & open main menu'
        )


@dp.message_handler(state=BroadcastInfo.message)
async def process_message(message: Message, state: FSMContext):
    for symbol in '[]()~`>#+-={}.!':
        message.text = message.text.replace(symbol, '\\' + symbol)
    message.text = message.text.replace('|', '||')
    async with state.proxy() as data:
        data['message'] = message.text
    await BroadcastInfo.next()
    user_amount = len(database.get_users())
    await message.reply(
        text=f"You sure you want to broadcast this message to *{user_amount}* users?\n\n{message.text}",
        parse_mode="MarkdownV2",
        reply_markup=generators.generate_confirmation_inline()
    )


@dp.callback_query_handler(lambda c: c.data.startswith('conf/'), state=BroadcastInfo.confirmation)
async def selected_confirmation_result(callback_query: CallbackQuery, state: FSMContext):
    await bot.edit_message_reply_markup(chat_id=callback_query.message.chat.id,
                                        message_id=callback_query.message.message_id)
    choice = callback_query.data.split('/')[1]
    if choice == 'sure':
        users = database.get_users()
        fail = 0
        async with state.proxy() as data:
            for user_id in users:
                try:
                    with open(f'images/happy.png', 'rb') as file:
                        await bot.send_photo(
                            chat_id=user_id,
                            caption=data['message'],
                            parse_mode='MarkdownV2',
                            reply_markup=generators.generate_investigate_inline(),
                            photo=file
                        )
                except Exception as ex:
                    fail += 1
        await bot.send_message(chat_id=callback_query.from_user.id,
                               text=f'Amount of users: {len(users)}\nFailed attempts: {fail}')
        logging.info(f'Broadcast message for {len(users)} users with {fail} users failed')
    await state.finish()
    await callback_query.answer('Complete')


@dp.message_handler()
async def unknown_message(message: Message):
    user_id = message.from_user.id

    date = generators.get_today()
    if is_offline(user_id):
        contains = generators.generate_date_image(date, user_id, SESSIONS.get(ADMIN_ID), rewrite=True, ignore_checked_in=True)
    else:
        contains = generators.generate_date_image(date, user_id, SESSIONS.get(user_id), rewrite=True)

    with open(f'images/{user_id if contains else "free"}.png', 'rb') as file:
        await bot.send_photo(
            chat_id=message.from_user.id,
            caption=generators.generate_date_caption(generators.get_today()),
            parse_mode="Markdown",
            reply_markup=generators.generate_date_inline(generators.get_today()),
            photo=file
        )


if __name__ == '__main__':
    update_session(ADMIN_ID)
    executor.start_polling(dp, skip_updates=True)
